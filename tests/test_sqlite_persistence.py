"""Tests for transactional SQLite registry and grant persistence."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loofy_extensions import (
    CapabilityGrant,
    ExtensionKey,
    ExtensionRegistry,
    ExtensionState,
    GrantAuthority,
    DuplicateExtensionVersionError,
)
from loofy_extensions.persistence import (
    CURRENT_SCHEMA_VERSION,
    SQLiteStore,
    SchemaVersionError,
    StorageClosedError,
)
from loofy_extensions.providers.github_gateway import OperationAuditEvent
from loofy_extensions.validation import DEFAULT_EXAMPLES


FIXED_NOW = datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc)


def manifest() -> dict[str, object]:
    return json.loads(
        next(DEFAULT_EXAMPLES.rglob("extension.json")).read_text(encoding="utf-8")
    )


class SQLitePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "registry.sqlite3"
        self.store = SQLiteStore(self.database_path)
        self.registry = ExtensionRegistry(store=self.store)
        self.record = self.registry.register(manifest())

    def tearDown(self) -> None:
        self.store.close()
        self.temporary_directory.cleanup()

    def test_schema_migration_and_integrity_check(self) -> None:
        self.assertEqual(self.store.schema_version, CURRENT_SCHEMA_VERSION)
        self.assertEqual(self.store.integrity_check(), ("ok",))

    def test_v1_schema_migrates_forward_to_operation_audit_v2(self) -> None:
        self.store.close()
        raw = sqlite3.connect(self.database_path)
        raw.execute("DROP INDEX IF EXISTS idx_operation_audit_scope_time")
        raw.execute("DROP INDEX IF EXISTS idx_operation_audit_correlation")
        raw.execute("DROP TABLE IF EXISTS operation_audit_events")
        raw.execute("DELETE FROM schema_migrations WHERE version > 1")
        raw.commit()
        raw.close()

        upgraded_store = SQLiteStore(self.database_path)
        self.store = upgraded_store
        self.assertEqual(upgraded_store.schema_version, 2)
        self.assertEqual(upgraded_store.events, ())
        self.assertEqual(upgraded_store.integrity_check(), ("ok",))

    def test_operation_audit_events_survive_restart(self) -> None:
        event = OperationAuditEvent(
            event_type="repository.metadata.read",
            extension_id="com.example.extension",
            extension_version="1.2.3",
            manifest_digest="sha256:abc",
            principal_id="user:alice",
            tenant_id="tenant:alpha",
            capability="repository.metadata.read",
            resource_id="github:repository:owner/repo",
            environment="test",
            outcome="succeeded",
            decision_code="ok",
            occurred_at=FIXED_NOW,
            source_id="77",
            correlation_id="correlation-001",
        )
        self.store.append(event)
        self.assertEqual(self.store.events, (event,))
        self.store.close()

        reopened_store = SQLiteStore(self.database_path)
        self.store = reopened_store
        self.assertEqual(reopened_store.events, (event,))
        self.assertEqual(reopened_store.events[0].correlation_id, "correlation-001")

    def test_registry_record_and_lifecycle_audit_survive_restart(self) -> None:
        evaluating = self.registry.transition(
            self.record.key.extension_id,
            self.record.key.version,
            ExtensionState.EVALUATING,
            actor="reviewer",
            reason="begin review",
            occurred_at=FIXED_NOW,
        )
        approved = self.registry.transition(
            evaluating.key.extension_id,
            evaluating.key.version,
            ExtensionState.APPROVED,
            actor="reviewer",
            reason="review accepted",
            approval_ref="review:sqlite-test",
            occurred_at=FIXED_NOW + timedelta(seconds=1),
        )
        original_events = self.registry.audit_events
        self.assertEqual(len(original_events), 2)
        self.store.close()

        reopened_store = SQLiteStore(self.database_path)
        self.store = reopened_store
        self.registry = ExtensionRegistry(store=reopened_store)
        restored = self.registry.get(approved.key.extension_id, approved.key.version)
        self.assertEqual(restored.state, ExtensionState.APPROVED)
        self.assertEqual(restored.manifest_digest, self.record.manifest_digest)
        self.assertEqual(self.registry.list_extensions(state=ExtensionState.APPROVED), (restored,))
        self.assertEqual(self.registry.audit_events, original_events)
        self.assertEqual(self.store.integrity_check(), ("ok",))

    def test_same_version_digest_conflict_is_rejected(self) -> None:
        changed = manifest()
        changed["metadata"]["description"] = "changed without a version bump"
        with self.assertRaises(DuplicateExtensionVersionError):
            self.registry.register(changed)
        self.assertEqual(len(self.registry.list_extensions()), 1)

    def test_lifecycle_state_and_audit_event_roll_back_together(self) -> None:
        self.registry.transition(
            self.record.key.extension_id,
            self.record.key.version,
            ExtensionState.EVALUATING,
            actor="reviewer",
            reason="begin review",
            occurred_at=FIXED_NOW,
        )
        prior_events = self.registry.audit_events
        self.store._connection.execute(
            """
            CREATE TRIGGER fail_lifecycle_audit
            BEFORE INSERT ON lifecycle_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'injected audit failure');
            END
            """
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.registry.transition(
                self.record.key.extension_id,
                self.record.key.version,
                ExtensionState.APPROVED,
                actor="reviewer",
                reason="review accepted",
                approval_ref="review:sqlite-test",
                occurred_at=FIXED_NOW + timedelta(seconds=1),
            )
        restored = self.registry.get(self.record.key.extension_id, self.record.key.version)
        self.assertEqual(restored.state, ExtensionState.EVALUATING)
        self.assertEqual(self.registry.audit_events, prior_events)

    def test_grant_and_audit_survive_restart_and_revocation_is_durable(self) -> None:
        record = self.registry.transition(
            self.record.key.extension_id,
            self.record.key.version,
            ExtensionState.EVALUATING,
            actor="reviewer",
            reason="begin grant test review",
            occurred_at=FIXED_NOW,
        )
        record = self.registry.transition(
            record.key.extension_id,
            record.key.version,
            ExtensionState.APPROVED,
            actor="reviewer",
            reason="approve grant test extension",
            approval_ref="review:sqlite-grant-test",
            occurred_at=FIXED_NOW + timedelta(seconds=1),
        )
        record = self.registry.transition(
            record.key.extension_id,
            record.key.version,
            ExtensionState.INSTALLED,
            actor="operator",
            reason="install reference record",
            occurred_at=FIXED_NOW + timedelta(seconds=2),
        )
        record = self.registry.transition(
            record.key.extension_id,
            record.key.version,
            ExtensionState.CONFIGURED,
            actor="operator",
            reason="configure reference record",
            occurred_at=FIXED_NOW + timedelta(seconds=3),
        )
        record = self.registry.transition(
            record.key.extension_id,
            record.key.version,
            ExtensionState.VALIDATED,
            actor="operator",
            reason="validate reference record",
            occurred_at=FIXED_NOW + timedelta(seconds=4),
        )
        record = self.registry.transition(
            record.key.extension_id,
            record.key.version,
            ExtensionState.ENABLED,
            actor="owner:reviewer",
            reason="enable for grant persistence test",
            occurred_at=FIXED_NOW + timedelta(seconds=5),
        )
        key = record.key
        authority = GrantAuthority(
            self.store,
            record_loader=lambda requested_key: self.registry.get(
                requested_key.extension_id, requested_key.version
            ),
            tenant_member_verifier=lambda principal, tenant: (
                principal in {"user:reader", "owner:reviewer"} and tenant == "tenant:alpha"
            ),
            grant_scope_authorizer=lambda actor, tenant, capability, resource, environment: (
                actor == "owner:reviewer"
                and tenant == "tenant:alpha"
                and capability == "repository.contents.read"
                and resource == "repo:owner/name"
                and environment == "test"
            ),
            clock=lambda: FIXED_NOW,
            grant_id_factory=lambda: "grant-sqlite-001",
        )
        grant = authority.issue_grant(
            key=key,
            principal_id="user:reader",
            tenant_id="tenant:alpha",
            capability="repository.contents.read",
            resource_id="repo:owner/name",
            environment="test",
            actor_id="owner:reviewer",
            reason="allow metadata inspection",
            expires_at=FIXED_NOW + timedelta(hours=1),
        )
        self.assertEqual(self.store.active_grants(), (grant,))
        self.assertEqual([event.event_type for event in self.store.grant_audit_events], ["issued"])
        self.store.close()

        reopened_store = SQLiteStore(self.database_path)
        self.store = reopened_store
        self.registry = ExtensionRegistry(store=reopened_store)
        self.assertEqual(reopened_store.active_grants(), (grant,))
        self.assertEqual([event.event_type for event in reopened_store.grant_audit_events], ["issued"])

        reopened_authority = GrantAuthority(
            reopened_store,
            record_loader=lambda requested_key: self.registry.get(
                requested_key.extension_id, requested_key.version
            ),
            tenant_member_verifier=lambda principal, tenant: (
                principal in {"user:reader", "owner:reviewer"} and tenant == "tenant:alpha"
            ),
            grant_scope_authorizer=lambda actor, tenant, capability, resource, environment: (
                actor == "owner:reviewer"
                and tenant == "tenant:alpha"
                and resource == "repo:owner/name"
                and environment == "test"
            ),
            clock=lambda: FIXED_NOW + timedelta(seconds=2),
        )
        reopened_authority.revoke_grant(
            grant_id=grant.grant_id,
            actor_id="owner:reviewer",
            reason="access no longer needed",
        )
        self.assertEqual(reopened_store.active_grants(), ())
        self.assertTrue(reopened_store.is_revoked(grant.grant_id))
        self.assertEqual(
            [event.event_type for event in reopened_store.grant_audit_events],
            ["issued", "revoked"],
        )

    def test_grant_issue_rolls_back_when_audit_insert_fails(self) -> None:
        grant = CapabilityGrant(
            grant_id="grant-atomic",
            key=self.record.key,
            principal_id="user:reader",
            tenant_id="tenant:alpha",
            capability="repository.contents.read",
            resource_id="repo:owner/name",
            environment="test",
            granted_by="owner:reviewer",
            expires_at=FIXED_NOW + timedelta(hours=1),
        )
        self.store._connection.execute(
            """
            CREATE TRIGGER fail_grant_audit
            BEFORE INSERT ON grant_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'injected grant audit failure');
            END
            """
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.issue(grant, reason="atomicity test", occurred_at=FIXED_NOW)
        self.assertEqual(self.store.active_grants(), ())
        self.assertEqual(self.store.grant_audit_events, ())

    def test_grant_revoke_rolls_back_when_audit_insert_fails(self) -> None:
        grant = CapabilityGrant(
            grant_id="grant-revoke-atomic",
            key=self.record.key,
            principal_id="user:reader",
            tenant_id="tenant:alpha",
            capability="repository.contents.read",
            resource_id="repo:owner/name",
            environment="test",
            granted_by="owner:reviewer",
            expires_at=FIXED_NOW + timedelta(hours=1),
        )
        self.store.issue(grant, reason="test setup", occurred_at=FIXED_NOW)
        self.store._connection.execute(
            """
            CREATE TRIGGER fail_revoke_audit
            BEFORE INSERT ON grant_audit_events
            WHEN NEW.event_type = 'revoked'
            BEGIN
                SELECT RAISE(ABORT, 'injected revoke audit failure');
            END
            """
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.revoke(
                grant.grant_id,
                actor_id="owner:reviewer",
                reason="atomicity test",
                occurred_at=FIXED_NOW + timedelta(seconds=1),
            )
        self.assertEqual(self.store.active_grants(), (grant,))
        self.assertFalse(self.store.is_revoked(grant.grant_id))
        self.assertEqual([event.event_type for event in self.store.grant_audit_events], ["issued"])

    def test_schema_version_ahead_of_code_is_rejected(self) -> None:
        self.store.close()
        raw = sqlite3.connect(self.database_path)
        raw.execute(
            "DELETE FROM schema_migrations WHERE version < ?",
            (CURRENT_SCHEMA_VERSION,),
        )
        raw.execute(
            "UPDATE schema_migrations SET version = ?",
            (CURRENT_SCHEMA_VERSION + 1,),
        )
        raw.commit()
        raw.close()
        with self.assertRaises(SchemaVersionError):
            SQLiteStore(self.database_path)

    def test_closed_store_rejects_operations(self) -> None:
        self.store.close()
        with self.assertRaises(StorageClosedError):
            self.store.get_extension(self.record.key.extension_id, self.record.key.version)


if __name__ == "__main__":
    unittest.main()
