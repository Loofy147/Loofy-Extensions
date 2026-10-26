"""Tests for SQLite audit-chain integrity and tamper detection."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from loofy_extensions.persistence import CURRENT_SCHEMA_VERSION, SQLiteStore
from loofy_extensions.providers.github_gateway import OperationAuditEvent


def event(index: int) -> OperationAuditEvent:
    return OperationAuditEvent(
        event_type="operation",
        extension_id="com.example.extension",
        extension_version="1.0.0",
        manifest_digest="sha256:" + "a" * 64,
        principal_id="user:alice",
        tenant_id="tenant:alpha",
        capability="repository.metadata.read",
        resource_id="github:repository:owner/repo",
        environment="test",
        outcome="succeeded",
        decision_code="ok",
        occurred_at=datetime(2026, 10, 26, 12, index, tzinfo=timezone.utc),
        source_id="123",
        correlation_id=f"run-{index}",
    )


class AuditChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SQLiteStore(Path(self.temp.name) / "extensions.sqlite")
        self.addCleanup(self.store.close)

    def test_migration_adds_chain_and_clean_database_verifies(self) -> None:
        self.assertEqual(self.store.schema_version, CURRENT_SCHEMA_VERSION)
        self.assertEqual(self.store.verify_audit_chain(), ())

    def test_operation_events_are_chained_transactionally(self) -> None:
        self.store.append(event(1))
        self.store.append(event(2))
        self.assertEqual(self.store.verify_audit_chain(), ())
        rows = self.store._connection.execute(
            "SELECT sequence_id, previous_hash, event_hash FROM audit_chain ORDER BY sequence_id"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["previous_hash"], "")
        self.assertEqual(rows[1]["previous_hash"], rows[0]["event_hash"])
        self.assertNotEqual(rows[0]["event_hash"], rows[1]["event_hash"])

    def test_payload_modification_is_detected(self) -> None:
        self.store.append(event(1))
        self.store._connection.execute(
            "UPDATE audit_chain SET payload_json=? WHERE sequence_id=1",
            (json.dumps({"source_table": "operation_audit_events", "source_event_id": 1, "event": {"outcome": "forged"}}),),
        )
        errors = self.store.verify_audit_chain()
        self.assertIn("event-hash-mismatch:1", errors)

    def test_deleting_an_interior_chain_entry_is_detected(self) -> None:
        self.store.append(event(1))
        self.store.append(event(2))
        self.store.append(event(3))
        self.store._connection.execute("DELETE FROM audit_chain WHERE sequence_id=2")
        errors = self.store.verify_audit_chain()
        self.assertTrue(any(error.startswith("sequence-gap:2:") for error in errors))
        self.assertTrue(any(error.startswith("previous-hash-mismatch:") for error in errors))


if __name__ == "__main__":
    unittest.main()
