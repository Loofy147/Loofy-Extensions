"""Transactional SQLite persistence for extension registry and grant state.

This adapter is a local, single-database persistence reference. It uses explicit
schema migrations and transactions to persist records and their audit events
atomically. It is not a distributed database, identity provider, secret store,
or production service boundary.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from .providers.github_gateway import OperationAuditEvent

from .grants import GrantAuditEvent, GrantConflictError, GrantPolicyError
from .lifecycle import transition_record
from .models import AuditEvent, ExtensionKey, ExtensionRecord, ExtensionState
from .policy import CapabilityGrant


CURRENT_SCHEMA_VERSION = 2


class StorageError(RuntimeError):
    """Base error for persistence contract failures."""


class StorageClosedError(StorageError):
    """Raised after a store has been closed."""


class SchemaVersionError(StorageError):
    """Raised when a database schema is newer than this package supports."""


class ImmutableVersionConflictError(StorageError):
    """Raised when an existing extension version is registered with new content."""


def _timestamp_to_db(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _timestamp_from_db(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StorageError("persisted timestamp is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _json_list(values: frozenset[str]) -> str:
    return json.dumps(sorted(values), ensure_ascii=False, separators=(",", ":"))


def _read_string_set(value: str) -> frozenset[str]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise StorageError("persisted permission/capability collection is malformed")
    return frozenset(parsed)


class SQLiteStore:
    """SQLite-backed registry and grant store with atomic state/audit changes.

    Each lifecycle transition commits the extension state update and its audit
    event in the same transaction. Grant issue/revoke operations likewise commit
    grant state and the matching grant audit event atomically.

    Pass one database path to the extension registry and grant authority. A
    second SQLiteStore instance may open that same file after the first is closed.
    SQLite locking and BEGIN IMMEDIATE serialize writers; this is intended for a
    local, single-host deployment or test harness, not a multi-region service.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if str(path) != ":memory:":
            self.path = Path(path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            database_name = str(self.path)
        else:
            self.path = ":memory:"
            database_name = ":memory:"

        self._lock = RLock()
        self._closed = False
        self._connection = sqlite3.connect(
            database_name,
            timeout=timeout_seconds,
            check_same_thread=False,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute(f"PRAGMA busy_timeout = {int(timeout_seconds * 1000)}")
        if database_name != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        try:
            self._initialize_schema()
        except BaseException:
            self._connection.close()
            self._closed = True
            raise

    @property
    def schema_version(self) -> int:
        with self._lock:
            self._ensure_open()
            row = self._connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            return int(row["version"])

    @property
    def lifecycle_events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                "SELECT * FROM lifecycle_audit_events ORDER BY event_id"
            ).fetchall()
            return tuple(self._lifecycle_event_from_row(row) for row in rows)

    @property
    def grant_audit_events(self) -> tuple[GrantAuditEvent, ...]:
        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                "SELECT * FROM grant_audit_events ORDER BY event_id"
            ).fetchall()
            return tuple(self._grant_event_from_row(row) for row in rows)

    @property
    def events(self) -> tuple[OperationAuditEvent, ...]:
        """Return durable gateway audit events in insertion order."""
        from .providers.github_gateway import OperationAuditEvent

        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                "SELECT * FROM operation_audit_events ORDER BY event_id"
            ).fetchall()
            return tuple(
                OperationAuditEvent(
                    event_type=row["event_type"],
                    extension_id=row["extension_id"],
                    extension_version=row["extension_version"],
                    manifest_digest=row["manifest_digest"],
                    principal_id=row["principal_id"],
                    tenant_id=row["tenant_id"],
                    capability=row["capability"],
                    resource_id=row["resource_id"],
                    environment=row["environment"],
                    outcome=row["outcome"],
                    decision_code=row["decision_code"],
                    occurred_at=_timestamp_from_db(row["occurred_at"]),
                    source_id=row["source_id"],
                    correlation_id=row["correlation_id"],
                )
                for row in rows
            )

    @property
    def operation_audit_events(self) -> tuple[OperationAuditEvent, ...]:
        """Named alias for the event collection exposed to the gateway audit sink."""
        return self.events

    def append(self, event: OperationAuditEvent) -> None:
        """Durably append one operation event; compatible with OperationAuditSink."""
        required_fields = (
            "event_type",
            "extension_id",
            "extension_version",
            "manifest_digest",
            "principal_id",
            "tenant_id",
            "capability",
            "resource_id",
            "environment",
            "outcome",
            "decision_code",
            "correlation_id",
        )
        for field_name in required_fields:
            value = getattr(event, field_name, None)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"operation audit field {field_name} must be non-empty")
        occurred_at_db = _timestamp_to_db(event.occurred_at)
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO operation_audit_events (
                    event_type, extension_id, extension_version, manifest_digest,
                    principal_id, tenant_id, capability, resource_id, environment,
                    outcome, decision_code, occurred_at, source_id, correlation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_type,
                    event.extension_id,
                    event.extension_version,
                    event.manifest_digest,
                    event.principal_id,
                    event.tenant_id,
                    event.capability,
                    event.resource_id,
                    event.environment,
                    event.outcome,
                    event.decision_code,
                    occurred_at_db,
                    event.source_id,
                    event.correlation_id,
                ),
            )

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> "SQLiteStore":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._ensure_open()
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
                self._connection.execute("COMMIT")
            except BaseException:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def _initialize_schema(self) -> None:
        with self._lock:
            self._ensure_open()
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            row = self._connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            version = int(row["version"])
            if version > CURRENT_SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"Database schema version {version} is newer than supported version {CURRENT_SCHEMA_VERSION}."
                )
            if version == CURRENT_SCHEMA_VERSION:
                return

            # Re-read under the write transaction so simultaneous constructors
            # cannot both apply the same migration after observing an older version.
            with self._transaction() as connection:
                locked_row = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
                ).fetchone()
                locked_version = int(locked_row["version"])
                if locked_version > CURRENT_SCHEMA_VERSION:
                    raise SchemaVersionError(
                        f"Database schema version {locked_version} is newer than supported version {CURRENT_SCHEMA_VERSION}."
                    )
                while locked_version < CURRENT_SCHEMA_VERSION:
                    next_version = locked_version + 1
                    if next_version == 1:
                        self._migration_1(connection)
                    elif next_version == 2:
                        self._migration_2(connection)
                    else:
                        raise SchemaVersionError(
                            f"No migration path is defined to schema version {next_version}."
                        )
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (next_version, _timestamp_to_db(datetime.now(timezone.utc))),
                    )
                    locked_version = next_version

    @staticmethod
    def _migration_1(connection: sqlite3.Connection) -> None:
        statements = (
            """
            CREATE TABLE extension_records (
                extension_id TEXT NOT NULL,
                version TEXT NOT NULL,
                name TEXT NOT NULL,
                publisher TEXT NOT NULL,
                source TEXT NOT NULL,
                license TEXT NOT NULL,
                kind TEXT NOT NULL,
                manifest_digest TEXT NOT NULL,
                artifact_digest TEXT,
                source_revision TEXT,
                requested_permissions_json TEXT NOT NULL,
                provided_capabilities_json TEXT NOT NULL,
                required_capabilities_json TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (extension_id, version)
            )
            """,
            """
            CREATE TABLE lifecycle_audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                extension_id TEXT NOT NULL,
                version TEXT NOT NULL,
                from_state TEXT NOT NULL,
                to_state TEXT NOT NULL,
                actor TEXT NOT NULL,
                reason TEXT NOT NULL,
                approval_ref TEXT,
                occurred_at TEXT NOT NULL,
                FOREIGN KEY (extension_id, version)
                    REFERENCES extension_records(extension_id, version)
                    ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE capability_grants (
                grant_id TEXT PRIMARY KEY,
                extension_id TEXT NOT NULL,
                extension_version TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                capability TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                granted_by TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                approval_ref TEXT,
                issued_at TEXT NOT NULL,
                revoked_at TEXT,
                FOREIGN KEY (extension_id, extension_version)
                    REFERENCES extension_records(extension_id, version)
                    ON DELETE RESTRICT
            )
            """,
            """
            CREATE TABLE grant_audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL CHECK (event_type IN ('issued', 'revoked')),
                grant_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                extension_id TEXT NOT NULL,
                extension_version TEXT NOT NULL,
                capability TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                reason TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                FOREIGN KEY (grant_id) REFERENCES capability_grants(grant_id)
                    ON DELETE RESTRICT
            )
            """,
            "CREATE INDEX idx_extension_records_state ON extension_records(state)",
            "CREATE INDEX idx_grants_scope ON capability_grants(tenant_id, principal_id, capability, resource_id, environment)",
            "CREATE INDEX idx_grants_extension ON capability_grants(extension_id, extension_version)",
            "CREATE INDEX idx_lifecycle_audit_key ON lifecycle_audit_events(extension_id, version, event_id)",
            "CREATE INDEX idx_grant_audit_grant ON grant_audit_events(grant_id, event_id)",
        )
        for statement in statements:
            connection.execute(statement)

    @staticmethod
    def _migration_2(connection: sqlite3.Connection) -> None:
        """Add durable gateway operation audit and correlation identifiers."""
        connection.execute(
            """
            CREATE TABLE operation_audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                extension_id TEXT NOT NULL,
                extension_version TEXT NOT NULL,
                manifest_digest TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                capability TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                outcome TEXT NOT NULL,
                decision_code TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                source_id TEXT,
                correlation_id TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX idx_operation_audit_scope_time ON operation_audit_events(tenant_id, resource_id, occurred_at, event_id)"
        )
        connection.execute(
            "CREATE INDEX idx_operation_audit_correlation ON operation_audit_events(correlation_id, event_id)"
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise StorageClosedError("SQLiteStore is closed")

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> ExtensionRecord:
        return ExtensionRecord(
            key=ExtensionKey(row["extension_id"], row["version"]),
            name=row["name"],
            publisher=row["publisher"],
            source=row["source"],
            license=row["license"],
            kind=row["kind"],
            manifest_digest=row["manifest_digest"],
            artifact_digest=row["artifact_digest"],
            source_revision=row["source_revision"],
            requested_permissions=_read_string_set(row["requested_permissions_json"]),
            provided_capabilities=_read_string_set(row["provided_capabilities_json"]),
            required_capabilities=_read_string_set(row["required_capabilities_json"]),
            state=ExtensionState(row["state"]),
            created_at=_timestamp_from_db(row["created_at"]),
            updated_at=_timestamp_from_db(row["updated_at"]),
        )

    @staticmethod
    def _lifecycle_event_from_row(row: sqlite3.Row) -> AuditEvent:
        return AuditEvent(
            key=ExtensionKey(row["extension_id"], row["version"]),
            from_state=ExtensionState(row["from_state"]),
            to_state=ExtensionState(row["to_state"]),
            actor=row["actor"],
            reason=row["reason"],
            approval_ref=row["approval_ref"],
            occurred_at=_timestamp_from_db(row["occurred_at"]),
        )

    @staticmethod
    def _grant_from_row(row: sqlite3.Row) -> CapabilityGrant:
        return CapabilityGrant(
            grant_id=row["grant_id"],
            key=ExtensionKey(row["extension_id"], row["extension_version"]),
            principal_id=row["principal_id"],
            tenant_id=row["tenant_id"],
            capability=row["capability"],
            resource_id=row["resource_id"],
            environment=row["environment"],
            granted_by=row["granted_by"],
            expires_at=_timestamp_from_db(row["expires_at"]),
            approval_ref=row["approval_ref"],
        )

    @staticmethod
    def _grant_event_from_row(row: sqlite3.Row) -> GrantAuditEvent:
        return GrantAuditEvent(
            event_type=row["event_type"],
            grant_id=row["grant_id"],
            actor_id=row["actor_id"],
            principal_id=row["principal_id"],
            tenant_id=row["tenant_id"],
            extension_id=row["extension_id"],
            extension_version=row["extension_version"],
            capability=row["capability"],
            resource_id=row["resource_id"],
            environment=row["environment"],
            reason=row["reason"],
            occurred_at=_timestamp_from_db(row["occurred_at"]),
        )

    @staticmethod
    def _record_values(record: ExtensionRecord) -> tuple[object, ...]:
        return (
            record.key.extension_id,
            record.key.version,
            record.name,
            record.publisher,
            record.source,
            record.license,
            record.kind,
            record.manifest_digest,
            record.artifact_digest,
            record.source_revision,
            _json_list(record.requested_permissions),
            _json_list(record.provided_capabilities),
            _json_list(record.required_capabilities),
            record.state.value,
            _timestamp_to_db(record.created_at),
            _timestamp_to_db(record.updated_at),
        )

    def register_extension(self, record: ExtensionRecord) -> ExtensionRecord:
        """Persist a validated record; exact same version/digest is idempotent."""
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM extension_records WHERE extension_id=? AND version=?",
                (record.key.extension_id, record.key.version),
            ).fetchone()
            if existing is not None:
                if existing["manifest_digest"] != record.manifest_digest:
                    raise ImmutableVersionConflictError(
                        f"{record.key.extension_id}@{record.key.version} already exists with a different manifest digest."
                    )
                return self._record_from_row(existing)

            connection.execute(
                """
                INSERT INTO extension_records (
                    extension_id, version, name, publisher, source, license, kind,
                    manifest_digest, artifact_digest, source_revision,
                    requested_permissions_json, provided_capabilities_json,
                    required_capabilities_json, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._record_values(record),
            )
        return record

    def get_extension(self, extension_id: str, version: str) -> ExtensionRecord:
        with self._lock:
            self._ensure_open()
            row = self._connection.execute(
                "SELECT * FROM extension_records WHERE extension_id=? AND version=?",
                (extension_id, version),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown extension {extension_id}@{version}")
            return self._record_from_row(row)

    def list_extensions(
        self,
        *,
        state: ExtensionState | None = None,
    ) -> tuple[ExtensionRecord, ...]:
        with self._lock:
            self._ensure_open()
            if state is None:
                rows = self._connection.execute(
                    "SELECT * FROM extension_records ORDER BY extension_id, version"
                ).fetchall()
            else:
                rows = self._connection.execute(
                    "SELECT * FROM extension_records WHERE state=? ORDER BY extension_id, version",
                    (state.value,),
                ).fetchall()
            return tuple(self._record_from_row(row) for row in rows)

    def transition_extension(
        self,
        extension_id: str,
        version: str,
        target: ExtensionState,
        *,
        actor: str,
        reason: str,
        approval_ref: str | None = None,
        occurred_at: datetime | None = None,
    ) -> ExtensionRecord:
        """Commit state change and audit event atomically under a write lock."""
        key = ExtensionKey(extension_id, version)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM extension_records WHERE extension_id=? AND version=?",
                (extension_id, version),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown extension {extension_id}@{version}")
            current = self._record_from_row(row)
            updated, event = transition_record(
                current,
                target,
                actor=actor,
                reason=reason,
                approval_ref=approval_ref,
                occurred_at=occurred_at,
            )
            connection.execute(
                """
                UPDATE extension_records
                SET state=?, updated_at=?
                WHERE extension_id=? AND version=?
                """,
                (
                    updated.state.value,
                    _timestamp_to_db(updated.updated_at),
                    key.extension_id,
                    key.version,
                ),
            )
            self._insert_lifecycle_event(connection, event)
        return updated

    @staticmethod
    def _insert_lifecycle_event(connection: sqlite3.Connection, event: AuditEvent) -> None:
        connection.execute(
            """
            INSERT INTO lifecycle_audit_events (
                extension_id, version, from_state, to_state, actor, reason,
                approval_ref, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.key.extension_id,
                event.key.version,
                event.from_state.value,
                event.to_state.value,
                event.actor,
                event.reason,
                event.approval_ref,
                _timestamp_to_db(event.occurred_at),
            ),
        )

    @property
    def audit_events(self) -> tuple[GrantAuditEvent, ...]:
        """Alias for grant audit events to satisfy the grant-store contract."""
        return self.grant_audit_events

    def active_grants(self) -> tuple[CapabilityGrant, ...]:
        with self._lock:
            self._ensure_open()
            rows = self._connection.execute(
                "SELECT * FROM capability_grants WHERE revoked_at IS NULL ORDER BY grant_id"
            ).fetchall()
            return tuple(self._grant_from_row(row) for row in rows)

    def get(self, grant_id: str) -> CapabilityGrant:
        with self._lock:
            self._ensure_open()
            row = self._connection.execute(
                "SELECT * FROM capability_grants WHERE grant_id=?",
                (grant_id,),
            ).fetchone()
            if row is None:
                raise GrantPolicyError("grant-not-found", "The requested grant does not exist.")
            return self._grant_from_row(row)

    def is_revoked(self, grant_id: str) -> bool:
        with self._lock:
            self._ensure_open()
            row = self._connection.execute(
                "SELECT revoked_at FROM capability_grants WHERE grant_id=?",
                (grant_id,),
            ).fetchone()
            if row is None:
                raise GrantPolicyError("grant-not-found", "The requested grant does not exist.")
            return row["revoked_at"] is not None

    def issue(
        self,
        grant: CapabilityGrant,
        *,
        reason: str,
        occurred_at: datetime,
    ) -> CapabilityGrant:
        """Persist a grant and its issued event in one transaction."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason is required")
        _timestamp_to_db(occurred_at)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM capability_grants WHERE grant_id=?",
                (grant.grant_id,),
            ).fetchone()
            if existing is not None:
                existing_grant = self._grant_from_row(existing)
                if existing_grant != grant:
                    raise GrantConflictError(
                        "grant ID already exists with different immutable content"
                    )
                if existing["revoked_at"] is not None:
                    raise GrantPolicyError(
                        "grant-id-revoked", "A revoked grant ID cannot be reissued."
                    )
                return existing_grant

            extension_exists = connection.execute(
                "SELECT 1 FROM extension_records WHERE extension_id=? AND version=?",
                (grant.key.extension_id, grant.key.version),
            ).fetchone()
            if extension_exists is None:
                raise GrantPolicyError(
                    "extension-unavailable",
                    "The grant's extension version is not present in the durable registry.",
                )

            connection.execute(
                """
                INSERT INTO capability_grants (
                    grant_id, extension_id, extension_version, principal_id, tenant_id,
                    capability, resource_id, environment, granted_by, expires_at,
                    approval_ref, issued_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    grant.grant_id,
                    grant.key.extension_id,
                    grant.key.version,
                    grant.principal_id,
                    grant.tenant_id,
                    grant.capability,
                    grant.resource_id,
                    grant.environment,
                    grant.granted_by,
                    _timestamp_to_db(grant.expires_at),
                    grant.approval_ref,
                    _timestamp_to_db(occurred_at),
                ),
            )
            self._insert_grant_event(
                connection, "issued", grant, grant.granted_by, reason, occurred_at
            )
        return grant

    def revoke(
        self,
        grant_id: str,
        *,
        actor_id: str,
        reason: str,
        occurred_at: datetime,
    ) -> CapabilityGrant:
        """Persist revocation and its audit event atomically."""
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError("actor_id is required")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason is required")
        occurred_at_db = _timestamp_to_db(occurred_at)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM capability_grants WHERE grant_id=?",
                (grant_id,),
            ).fetchone()
            if row is None:
                raise GrantPolicyError("grant-not-found", "The requested grant does not exist.")
            if row["revoked_at"] is not None:
                raise GrantPolicyError("grant-already-revoked", "The grant is already revoked.")
            grant = self._grant_from_row(row)
            connection.execute(
                "UPDATE capability_grants SET revoked_at=? WHERE grant_id=? AND revoked_at IS NULL",
                (occurred_at_db, grant_id),
            )
            self._insert_grant_event(
                connection, "revoked", grant, actor_id, reason, occurred_at
            )
        return grant

    @staticmethod
    def _insert_grant_event(
        connection: sqlite3.Connection,
        event_type: str,
        grant: CapabilityGrant,
        actor_id: str,
        reason: str,
        occurred_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO grant_audit_events (
                event_type, grant_id, actor_id, principal_id, tenant_id,
                extension_id, extension_version, capability, resource_id,
                environment, reason, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                grant.grant_id,
                actor_id.strip(),
                grant.principal_id,
                grant.tenant_id,
                grant.key.extension_id,
                grant.key.version,
                grant.capability,
                grant.resource_id,
                grant.environment,
                reason.strip(),
                _timestamp_to_db(occurred_at),
            ),
        )

    def integrity_check(self) -> tuple[str, ...]:
        """Return SQLite integrity and foreign-key checks; ('ok',) means clean."""
        with self._lock:
            self._ensure_open()
            integrity_rows = self._connection.execute("PRAGMA integrity_check").fetchall()
            foreign_key_rows = self._connection.execute("PRAGMA foreign_key_check").fetchall()
            messages = tuple(str(row[0]) for row in integrity_rows)
            if foreign_key_rows:
                return messages + (f"foreign_key_violations:{len(foreign_key_rows)}",)
            return messages
