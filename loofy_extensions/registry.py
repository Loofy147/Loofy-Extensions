"""Validated registry with optional durable storage; no external code is executed."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Protocol

from .lifecycle import transition_record
from .models import AuditEvent, ExtensionKey, ExtensionRecord, ExtensionState
from .validation import DEFAULT_SCHEMA, load_schema, validate_manifest_data


class ManifestValidationError(ValueError):
    """Raised when a candidate manifest violates the published schema."""


class DuplicateExtensionVersionError(ValueError):
    """Raised when a publisher attempts to replace an existing version in place."""


class RegistryStore(Protocol):
    """Persistence contract consumed by the registry facade."""

    @property
    def lifecycle_events(self) -> tuple[AuditEvent, ...]: ...

    def register_extension(self, record: ExtensionRecord) -> ExtensionRecord: ...

    def get_extension(self, extension_id: str, version: str) -> ExtensionRecord: ...

    def list_extensions(
        self, *, state: ExtensionState | None = None
    ) -> tuple[ExtensionRecord, ...]: ...

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
    ) -> ExtensionRecord: ...


class ExtensionRegistry:
    """Schema-backed registry facade with optional process-local or durable state.

    Without a store, behavior remains process-local and thread-safe for tests.
    When given a store implementing RegistryStore, persisted records and
    lifecycle transitions are read/written there; durable implementations should
    atomically commit state changes with their audit event.
    """

    def __init__(
        self,
        schema_path: Path = DEFAULT_SCHEMA,
        *,
        store: RegistryStore | None = None,
    ) -> None:
        self._schema = load_schema(schema_path)
        self._store = store
        self._records: dict[ExtensionKey, ExtensionRecord] = {}
        self._audit_events: list[AuditEvent] = []
        self._lock = RLock()

    @property
    def audit_events(self) -> tuple[AuditEvent, ...]:
        if self._store is not None:
            return self._store.lifecycle_events
        with self._lock:
            return tuple(self._audit_events)

    def register(self, manifest: Mapping[str, Any]) -> ExtensionRecord:
        """Validate and register a manifest; repeated identical registration is safe."""
        if not isinstance(manifest, Mapping):
            raise ManifestValidationError("manifest must be a JSON object")
        document = dict(manifest)
        errors = validate_manifest_data(document, self._schema)
        if errors:
            raise ManifestValidationError("; ".join(errors))

        metadata = document["metadata"]
        runtime = document["runtime"]
        key = ExtensionKey(metadata["id"], metadata["version"])
        canonical_json = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        manifest_digest = "sha256:" + hashlib.sha256(canonical_json).hexdigest()
        artifact = runtime.get("artifact") or {}

        record = ExtensionRecord(
            key=key,
            name=metadata["name"],
            publisher=metadata["publisher"],
            source=metadata["source"],
            license=metadata["license"],
            kind=runtime["type"],
            manifest_digest=manifest_digest,
            artifact_digest=artifact.get("digest"),
            source_revision=artifact.get("revision"),
            requested_permissions=frozenset(document["permissions"]["requested"]),
            provided_capabilities=frozenset(document["capabilities"]["provides"]),
            required_capabilities=frozenset(document["capabilities"]["requires"]),
        )

        if self._store is not None:
            # Import lazily to avoid coupling the facade to a concrete adapter.
            try:
                return self._store.register_extension(record)
            except Exception as exc:
                from .persistence import ImmutableVersionConflictError

                if isinstance(exc, ImmutableVersionConflictError):
                    raise DuplicateExtensionVersionError(str(exc)) from exc
                raise

        with self._lock:
            existing = self._records.get(key)
            if existing:
                if existing.manifest_digest != manifest_digest:
                    raise DuplicateExtensionVersionError(
                        f"{key.extension_id}@{key.version} already exists with a different manifest digest; publish a new version instead"
                    )
                return existing
            self._records[key] = record
            return record

    def get(self, extension_id: str, version: str) -> ExtensionRecord:
        if self._store is not None:
            return self._store.get_extension(extension_id, version)
        with self._lock:
            return self._records[ExtensionKey(extension_id, version)]

    def list_extensions(
        self,
        *,
        state: ExtensionState | None = None,
    ) -> tuple[ExtensionRecord, ...]:
        if self._store is not None:
            return self._store.list_extensions(state=state)
        with self._lock:
            records = sorted(self._records.values(), key=lambda item: item.key)
            if state is not None:
                records = [record for record in records if record.state == state]
            return tuple(records)

    def transition(
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
        """Apply an allowed transition and append its audit event."""
        if self._store is not None:
            return self._store.transition_extension(
                extension_id,
                version,
                target,
                actor=actor,
                reason=reason,
                approval_ref=approval_ref,
                occurred_at=occurred_at,
            )

        key = ExtensionKey(extension_id, version)
        with self._lock:
            try:
                current = self._records[key]
            except KeyError as exc:
                raise KeyError(f"unknown extension {extension_id}@{version}") from exc
            updated, event = transition_record(
                current,
                target,
                actor=actor,
                reason=reason,
                approval_ref=approval_ref,
                occurred_at=occurred_at,
            )
            self._records[key] = updated
            self._audit_events.append(event)
            return updated
