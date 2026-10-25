"""End-to-end tests for capability-backed authorization of validation tasks."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loofy_extensions import (
    ExtensionRegistry,
    ExtensionState,
    GrantAuthority,
    SQLiteStore,
)
from loofy_extensions.task_gateway import (
    AuthorizedTaskRunner,
    CapabilityTaskAuthorizer,
    TaskAuthorizationError,
    TaskCallerContext,
)
from loofy_extensions.tasks import ExecutionEnvelope, TaskRunner
from loofy_extensions.validation import DEFAULT_EXAMPLES


FIXED_NOW = datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc)
TASK_EXTENSION_ID = "com.loofy.extensions.task-runner"
TASK_EXTENSION_VERSION = "1.0.0"
TASK_CAPABILITY = "task.manifest.validate"
RESOURCE_ID = "extension-candidate:sample"


def task_runner_manifest() -> dict[str, object]:
    path = DEFAULT_EXAMPLES / "task-runner" / "extension.json"
    return json.loads(path.read_text(encoding="utf-8"))

def task_envelope(run_id: str) -> ExecutionEnvelope:
    return ExecutionEnvelope(
        run_id=run_id,
        task_id="manifest.validate",
        actor_id="untrusted:actor",
        tenant_id="untrusted:tenant",
        resource_id=RESOURCE_ID,
        environment="untrusted-environment",
        manifest=json.loads(
            (DEFAULT_EXAMPLES / "manifest-validator" / "extension.json").read_text(encoding="utf-8")
        ),
    )


class CapabilityTaskAuthorizationIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(Path(self.temporary_directory.name) / "task-auth.sqlite3")
        self.registry = ExtensionRegistry(store=self.store)
        record = self.registry.register(task_runner_manifest())
        transitions = (
            (ExtensionState.EVALUATING, {}),
            (ExtensionState.APPROVED, {"approval_ref": "review:task-runner"}),
            (ExtensionState.INSTALLED, {}),
            (ExtensionState.CONFIGURED, {}),
            (ExtensionState.VALIDATED, {}),
            (ExtensionState.ENABLED, {}),
        )
        for offset, (target, kwargs) in enumerate(transitions):
            record = self.registry.transition(
                record.key.extension_id,
                record.key.version,
                target,
                actor="test-owner",
                reason=f"register built-in task runner: {target.value}",
                occurred_at=FIXED_NOW + timedelta(seconds=offset),
                **kwargs,
            )
        self.record = record
        self.caller = TaskCallerContext(
            principal_id="user:alice",
            tenant_id="tenant:alpha",
            environment="test",
        )
        self.grant_authority = GrantAuthority(
            self.store,
            record_loader=lambda key: self.registry.get(key.extension_id, key.version),
            tenant_member_verifier=lambda principal, tenant: (
                principal in {"user:alice", "owner:alice"}
                and tenant == "tenant:alpha"
            ),
            grant_scope_authorizer=lambda actor, tenant, capability, resource, environment: (
                actor == "owner:alice"
                and tenant == "tenant:alpha"
                and capability == TASK_CAPABILITY
                and resource == RESOURCE_ID
                and environment == "test"
            ),
            clock=lambda: FIXED_NOW,
            grant_id_factory=lambda: "task-validation-grant-001",
        )
        self.grant = self.grant_authority.issue_grant(
            key=self.record.key,
            principal_id=self.caller.principal_id,
            tenant_id=self.caller.tenant_id,
            capability=TASK_CAPABILITY,
            resource_id=RESOURCE_ID,
            environment=self.caller.environment,
            actor_id="owner:alice",
            reason="allow the built-in validation task for this candidate",
            expires_at=FIXED_NOW + timedelta(hours=1),
        )
        self.authorizer = CapabilityTaskAuthorizer(
            extension_key=self.record.key,
            record_loader=lambda key: self.registry.get(key.extension_id, key.version),
            grants_loader=self.store.active_grants,
            clock=lambda: FIXED_NOW,
        )
        self.runner = TaskRunner(
            store=self.store,
            isolated_validation=True,
            clock=lambda: FIXED_NOW,
        )
        self.gateway = AuthorizedTaskRunner(
            self.runner,
            authorizer=self.authorizer,
            audit_sink=self.store,
            clock=lambda: FIXED_NOW,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temporary_directory.cleanup()

    def test_capability_grant_authorizes_isolated_task_and_persists_correlated_audit(self) -> None:
        result = self.gateway.run(task_envelope("task-authorized-001"), caller=self.caller)
        self.assertTrue(result.valid)
        self.assertEqual(result.actor_id, "user:alice")
        self.assertEqual(result.tenant_id, "tenant:alpha")
        self.assertEqual(result.environment, "test")
        self.assertEqual(self.store.task_run_results, (result,))
        self.assertEqual(
            [event.outcome for event in self.store.events],
            ["authorized", "succeeded"],
        )
        self.assertTrue(all(event.correlation_id == result.run_id for event in self.store.events))
        self.assertEqual(self.store.events[0].capability, TASK_CAPABILITY)
        self.assertEqual(self.store.events[-1].manifest_digest, result.input_digest)

    def test_revocation_blocks_following_task_before_runner_executes(self) -> None:
        first = self.gateway.run(task_envelope("task-before-revoke"), caller=self.caller)
        self.grant_authority.revoke_grant(
            grant_id=self.grant.grant_id,
            actor_id="owner:alice",
            reason="revoke task access after positive control",
        )
        with self.assertRaises(TaskAuthorizationError) as context:
            self.gateway.run(task_envelope("task-after-revoke"), caller=self.caller)
        self.assertEqual(context.exception.code, "no-matching-grant")
        self.assertEqual(self.store.task_run_results, (first,))
        self.assertEqual(self.store.events[-1].outcome, "denied")
        self.assertEqual(self.store.events[-1].decision_code, "no-matching-grant")

    def test_cross_tenant_caller_is_denied_by_the_capability_policy(self) -> None:
        other_tenant = TaskCallerContext(
            principal_id="user:alice",
            tenant_id="tenant:beta",
            environment="test",
        )
        with self.assertRaises(TaskAuthorizationError) as context:
            self.gateway.run(task_envelope("task-other-tenant"), caller=other_tenant)
        self.assertEqual(context.exception.code, "no-matching-grant")
        self.assertEqual(self.runner.history, ())
        self.assertEqual(self.store.events[-1].outcome, "denied")

    def test_disabled_task_extension_is_denied_even_when_grant_is_active(self) -> None:
        self.registry.transition(
            self.record.key.extension_id,
            self.record.key.version,
            ExtensionState.DISABLED,
            actor="owner:alice",
            reason="disable built-in task permission for test",
            occurred_at=FIXED_NOW + timedelta(minutes=1),
        )
        with self.assertRaises(TaskAuthorizationError) as context:
            self.gateway.run(task_envelope("task-disabled-extension"), caller=self.caller)
        self.assertEqual(context.exception.code, "extension-not-enabled")
        self.assertEqual(self.store.active_grants(), (self.grant,))
        self.assertEqual(self.runner.history, ())
        self.assertEqual(self.store.events[-1].outcome, "denied")


if __name__ == "__main__":
    unittest.main()
