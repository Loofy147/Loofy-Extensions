"""Regression tests for Phase 1 lifecycle and authorization contracts."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from loofy_extensions import (
    CapabilityGrant,
    CapabilityRequest,
    ExtensionRegistry,
    ExtensionState,
    LifecycleTransitionError,
    authorize,
)
from loofy_extensions.lifecycle import (
    CAPABILITY_RISK_POLICY_VERSION,
    is_high_impact_capability,
)
from loofy_extensions.validation import DEFAULT_EXAMPLES


def make_enabled_record(registry: ExtensionRegistry):
    manifest = json.loads(
        next(DEFAULT_EXAMPLES.rglob("extension.json")).read_text(encoding="utf-8")
    )
    record = registry.register(manifest)
    record = registry.transition(
        record.key.extension_id, record.key.version, ExtensionState.EVALUATING,
        actor="test", reason="begin review",
    )
    record = registry.transition(
        record.key.extension_id, record.key.version, ExtensionState.APPROVED,
        actor="reviewer", reason="review passed", approval_ref="review:test",
    )
    record = registry.transition(
        record.key.extension_id, record.key.version, ExtensionState.INSTALLED,
        actor="test", reason="install metadata",
    )
    record = registry.transition(
        record.key.extension_id, record.key.version, ExtensionState.CONFIGURED,
        actor="test", reason="configuration supplied",
    )
    record = registry.transition(
        record.key.extension_id, record.key.version, ExtensionState.VALIDATED,
        actor="test", reason="validation passed",
    )
    return registry.transition(
        record.key.extension_id, record.key.version, ExtensionState.ENABLED,
        actor="operator", reason="enable for test",
    )


class LifecycleContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ExtensionRegistry()
        self.record = make_enabled_record(self.registry)

    def test_update_can_recover_to_validated_state(self) -> None:
        key = self.record.key
        updating = self.registry.transition(
            key.extension_id, key.version, ExtensionState.UPDATING,
            actor="operator", reason="candidate update started",
        )
        recovered = self.registry.transition(
            key.extension_id, key.version, ExtensionState.VALIDATED,
            actor="operator", reason="candidate rejected; previous version revalidated",
        )
        self.assertEqual(updating.state, ExtensionState.UPDATING)
        self.assertEqual(recovered.state, ExtensionState.VALIDATED)
        self.assertEqual(self.registry.audit_events[-1].from_state, ExtensionState.UPDATING)
        self.assertEqual(self.registry.audit_events[-1].to_state, ExtensionState.VALIDATED)

    def test_blank_actor_and_reason_are_rejected(self) -> None:
        key = self.record.key
        with self.assertRaises(LifecycleTransitionError):
            self.registry.transition(
                key.extension_id, key.version, ExtensionState.DISABLED,
                actor="  ", reason="operator requested disable",
            )
        with self.assertRaises(LifecycleTransitionError):
            self.registry.transition(
                key.extension_id, key.version, ExtensionState.DISABLED,
                actor="operator", reason=" ",
            )

    def test_naive_transition_timestamp_is_rejected(self) -> None:
        key = self.record.key
        with self.assertRaises(LifecycleTransitionError):
            self.registry.transition(
                key.extension_id, key.version, ExtensionState.DISABLED,
                actor="operator", reason="timestamp contract test",
                occurred_at=datetime(2026, 1, 1),
            )

    def test_capability_risk_policy_is_explicitly_versioned(self) -> None:
        self.assertRegex(CAPABILITY_RISK_POLICY_VERSION, r"^\d+\.\d+\.\d+$")
        self.assertTrue(is_high_impact_capability("deployment.execute"))
        self.assertTrue(is_high_impact_capability("repository.contents.write"))
        self.assertTrue(is_high_impact_capability("secret.rotate"))
        self.assertFalse(is_high_impact_capability("repository.contents.read"))
        self.assertFalse(is_high_impact_capability("notifications.send"))


class GrantBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ExtensionRegistry()
        self.record = make_enabled_record(self.registry)
        self.now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
        self.request = CapabilityRequest(
            key=self.record.key,
            principal_id="user:test",
            tenant_id="tenant:test",
            capability="repository.contents.read",
            resource_id="repo:owner/name",
            environment="test",
        )
        self.grant = CapabilityGrant(
            grant_id="grant-boundary",
            key=self.record.key,
            principal_id=self.request.principal_id,
            tenant_id=self.request.tenant_id,
            capability=self.request.capability,
            resource_id=self.request.resource_id,
            environment=self.request.environment,
            granted_by="reviewer:test",
            expires_at=self.now + timedelta(seconds=30),
        )

    def test_grant_is_denied_at_exact_expiry_boundary(self) -> None:
        decision = authorize(
            self.record, self.request, (self.grant,),
            now=self.grant.expires_at,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "expired-or-unapproved-grant")

    def test_naive_grant_expiry_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CapabilityGrant(
                grant_id="grant-naive",
                key=self.record.key,
                principal_id=self.request.principal_id,
                capability=self.request.capability,
                resource_id=self.request.resource_id,
                environment=self.request.environment,
                granted_by="reviewer:test",
                expires_at=datetime(2026, 10, 25, 12, 0),
            )

    def test_naive_authorization_clock_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            authorize(
                self.record, self.request, (self.grant,),
                now=datetime(2026, 10, 25, 12, 0),
            )

    def test_duplicate_matching_grants_are_deterministic(self) -> None:
        later = CapabilityGrant(
            grant_id="grant-later",
            key=self.record.key,
            principal_id=self.request.principal_id,
            capability=self.request.capability,
            resource_id=self.request.resource_id,
            environment=self.request.environment,
            granted_by="reviewer:test",
            expires_at=self.now + timedelta(hours=2),
        )
        decision_forward = authorize(
            self.record, self.request, (self.grant, later), now=self.now,
        )
        decision_reverse = authorize(
            self.record, self.request, (later, self.grant), now=self.now,
        )
        self.assertEqual(decision_forward, decision_reverse)
        self.assertTrue(decision_forward.allowed)
        self.assertEqual(decision_forward.grant_id, "grant-boundary")


if __name__ == "__main__":
    unittest.main()
