"""Tests for the host authorization and audit boundary around validation tasks."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from loofy_extensions import SQLiteStore
from loofy_extensions.providers.github_gateway import InMemoryOperationAuditSink
from loofy_extensions.task_gateway import (
    AuthorizedTaskRunner,
    TaskAuthorizationContextUnavailable,
    TaskAuthorizationDecision,
    TaskAuthorizationError,
    TaskCallerContext,
)
from loofy_extensions.tasks import ExecutionEnvelope, TaskExecutionError, TaskRunner
from loofy_extensions.validation import DEFAULT_EXAMPLES


def sample_manifest() -> dict[str, object]:
    return json.loads(
        next(DEFAULT_EXAMPLES.rglob("extension.json")).read_text(encoding="utf-8")
    )


def envelope(
    *,
    run_id: str = "task-run-001",
    task_id: str = "manifest.validate",
    actor_id: str = "user:untrusted",
    tenant_id: str = "tenant:untrusted",
    environment: str = "untrusted-env",
    resource_id: str = "extension-candidate:sample",
    manifest: dict[str, object] | None = None,
) -> ExecutionEnvelope:
    return ExecutionEnvelope(
        run_id=run_id,
        task_id=task_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
        resource_id=resource_id,
        environment=environment,
        manifest=manifest if manifest is not None else sample_manifest(),
    )


class FakeAuthorizer:
    def __init__(self, decision=None, *, error: Exception | None = None) -> None:
        self.decision = decision or TaskAuthorizationDecision(True, "allowed", "policy accepted")
        self.error = error
        self.calls: list[dict[str, str]] = []

    def authorize(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.decision


class FailingAuditSink:
    def append(self, event) -> None:
        raise OSError("audit unavailable")


class AuthorizedTaskRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc)
        self.caller = TaskCallerContext(
            principal_id="user:alice",
            tenant_id="tenant:alpha",
            environment="test",
        )
        self.authorizer = FakeAuthorizer()
        self.audit = InMemoryOperationAuditSink()
        self.runner = TaskRunner(clock=lambda: self.now, monotonic=lambda: 1.0)
        self.gateway = AuthorizedTaskRunner(
            self.runner,
            authorizer=self.authorizer,
            audit_sink=self.audit,
            clock=lambda: self.now,
        )

    def test_trusted_caller_context_overrides_untrusted_envelope_identity(self) -> None:
        result = self.gateway.run(envelope(), caller=self.caller)
        self.assertTrue(result.valid)
        self.assertEqual(result.actor_id, "user:alice")
        self.assertEqual(result.tenant_id, "tenant:alpha")
        self.assertEqual(result.environment, "test")
        self.assertEqual(
            self.authorizer.calls,
            [{
                "principal_id": "user:alice",
                "tenant_id": "tenant:alpha",
                "task_id": "manifest.validate",
                "resource_id": "extension-candidate:sample",
                "environment": "test",
            }],
        )
        self.assertEqual(
            [event.outcome for event in self.audit.events],
            ["authorized", "succeeded"],
        )
        self.assertTrue(all(event.correlation_id == result.run_id for event in self.audit.events))
        self.assertEqual(self.audit.events[-1].manifest_digest, result.input_digest)
        self.assertEqual(self.audit.events[-1].decision_code, "ok")

    def test_policy_denial_is_audited_and_task_does_not_run(self) -> None:
        self.gateway = AuthorizedTaskRunner(
            self.runner,
            authorizer=FakeAuthorizer(
                TaskAuthorizationDecision(False, "tenant-policy-denied", "scope not allowed")
            ),
            audit_sink=self.audit,
            clock=lambda: self.now,
        )
        with self.assertRaises(TaskAuthorizationError) as context:
            self.gateway.run(envelope(), caller=self.caller)
        self.assertEqual(context.exception.code, "tenant-policy-denied")
        self.assertEqual(self.runner.history, ())
        self.assertEqual(len(self.audit.events), 1)
        self.assertEqual(self.audit.events[0].outcome, "denied")
        self.assertEqual(self.audit.events[0].tenant_id, "tenant:alpha")

    def test_authorizer_failure_fails_closed_and_is_audited(self) -> None:
        self.gateway = AuthorizedTaskRunner(
            self.runner,
            authorizer=FakeAuthorizer(error=RuntimeError("internal policy details")),
            audit_sink=self.audit,
            clock=lambda: self.now,
        )
        with self.assertRaises(TaskAuthorizationContextUnavailable) as context:
            self.gateway.run(envelope(), caller=self.caller)
        self.assertEqual(context.exception.code, "authorization-context-unavailable")
        self.assertNotIn("internal policy details", str(context.exception))
        self.assertEqual(self.runner.history, ())
        self.assertEqual(self.audit.events[0].decision_code, "authorization-context-unavailable")

    def test_pre_run_audit_failure_blocks_task(self) -> None:
        self.gateway = AuthorizedTaskRunner(
            self.runner,
            authorizer=self.authorizer,
            audit_sink=FailingAuditSink(),
            clock=lambda: self.now,
        )
        with self.assertRaises(OSError):
            self.gateway.run(envelope(), caller=self.caller)
        self.assertEqual(self.runner.history, ())

    def test_invalid_manifest_is_recorded_as_validation_failure(self) -> None:
        invalid = sample_manifest()
        del invalid["metadata"]["license"]
        result = self.gateway.run(
            envelope(run_id="invalid-task-run", manifest=invalid),
            caller=self.caller,
        )
        self.assertFalse(result.valid)
        self.assertEqual(result.outcome, "validation_failed")
        self.assertEqual(
            [event.outcome for event in self.audit.events],
            ["authorized", "validation_failed"],
        )
        self.assertEqual(self.audit.events[-1].decision_code, "manifest-schema-invalid")

    def test_oversized_input_is_audited_after_authorization(self) -> None:
        runner = TaskRunner(max_input_bytes=128)
        audit = InMemoryOperationAuditSink()
        gateway = AuthorizedTaskRunner(
            runner,
            authorizer=self.authorizer,
            audit_sink=audit,
            clock=lambda: self.now,
        )
        with self.assertRaises(TaskExecutionError) as context:
            gateway.run(envelope(run_id="oversized-run"), caller=self.caller)
        self.assertEqual(context.exception.code, "input-too-large")
        self.assertEqual(
            [event.outcome for event in audit.events],
            ["authorized", "task-error"],
        )
        self.assertEqual(audit.events[-1].decision_code, "input-too-large")
        self.assertEqual(runner.history, ())

    def test_unsupported_task_is_denied_without_authorizer_or_execution(self) -> None:
        with self.assertRaises(TaskAuthorizationError) as context:
            self.gateway.run(
                envelope(task_id="arbitrary.plugin.entrypoint"),
                caller=self.caller,
            )
        self.assertEqual(context.exception.code, "unsupported-task")
        self.assertEqual(self.authorizer.calls, [])
        self.assertEqual(self.runner.history, ())
        self.assertEqual(self.audit.events[0].outcome, "denied")

    def test_durable_task_result_and_audit_events_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "task-gateway.sqlite3"
            store = SQLiteStore(database_path)
            try:
                durable_runner = TaskRunner(store=store, clock=lambda: self.now, monotonic=lambda: 1.0)
                gateway = AuthorizedTaskRunner(
                    durable_runner,
                    authorizer=self.authorizer,
                    audit_sink=store,
                    clock=lambda: self.now,
                )
                request = envelope(run_id="durable-task-audit-001")
                first = gateway.run(request, caller=self.caller)
                self.assertEqual([event.outcome for event in store.events], ["authorized", "succeeded"])
                self.assertTrue(all(event.correlation_id == first.run_id for event in store.events))
                store.close()

                reopened = SQLiteStore(database_path)
                try:
                    self.assertEqual(len(reopened.task_run_results), 1)
                    self.assertEqual(len(reopened.events), 2)
                    self.assertEqual(reopened.task_run_results[0], first)
                    self.assertEqual(
                        [event.outcome for event in reopened.events],
                        ["authorized", "succeeded"],
                    )
                finally:
                    reopened.close()
            finally:
                store.close()

    def test_durable_audit_failure_prevents_task_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = SQLiteStore(Path(temporary_directory) / "task-audit-failure.sqlite3")
            try:
                store._connection.execute(
                    """
                    CREATE TRIGGER fail_task_audit
                    BEFORE INSERT ON operation_audit_events
                    BEGIN
                        SELECT RAISE(ABORT, 'injected operation audit failure');
                    END
                    """
                )
                runner = TaskRunner(store=store)
                gateway = AuthorizedTaskRunner(
                    runner,
                    authorizer=self.authorizer,
                    audit_sink=store,
                    clock=lambda: self.now,
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    gateway.run(envelope(), caller=self.caller)
                self.assertEqual(runner.history, ())
                self.assertEqual(store.task_run_results, ())
                self.assertEqual(store.events, ())
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
