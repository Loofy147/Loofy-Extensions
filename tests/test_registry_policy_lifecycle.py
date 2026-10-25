"""Behavioral tests for the non-executing reference registry and policy model."""

from __future__ import annotations

import copy
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from loofy_extensions import (
    CapabilityGrant,
    CapabilityRequest,
    ExtensionKey,
    ExtensionRegistry,
    ExtensionState,
    LifecycleTransitionError,
    ManifestValidationError,
    DuplicateExtensionVersionError,
    authorize,
)

from loofy_extensions.validation import DEFAULT_EXAMPLES


def enabled_record(registry: ExtensionRegistry):
    record = registry.register(
        json.loads((DEFAULT_EXAMPLES / "manifest-validator" / "extension.json").read_text(encoding="utf-8"))
    )
    record = registry.transition(record.key.extension_id, record.key.version, ExtensionState.EVALUATING, actor="test", reason="begin review")
    record = registry.transition(record.key.extension_id, record.key.version, ExtensionState.APPROVED, actor="reviewer", reason="review passed", approval_ref="review:unit-test")
    record = registry.transition(record.key.extension_id, record.key.version, ExtensionState.INSTALLED, actor="test", reason="install metadata")
    record = registry.transition(record.key.extension_id, record.key.version, ExtensionState.CONFIGURED, actor="test", reason="configuration supplied")
    record = registry.transition(record.key.extension_id, record.key.version, ExtensionState.VALIDATED, actor="test", reason="contract checks passed")
    record = registry.transition(record.key.extension_id, record.key.version, ExtensionState.ENABLED, actor="operator", reason="enable read-only example")
    return record


class ExtensionRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ExtensionRegistry()
        self.sample_path = (DEFAULT_EXAMPLES / "manifest-validator" / "extension.json")
        self.sample = json.loads(self.sample_path.read_text(encoding="utf-8"))

    def test_register_validates_and_starts_discovered(self) -> None:
        record = self.registry.register(self.sample)
        self.assertEqual(record.state, ExtensionState.DISCOVERED)
        self.assertTrue(record.manifest_digest.startswith("sha256:"))
        self.assertEqual(len(self.registry.list_extensions()), 1)

    def test_identical_registration_is_idempotent(self) -> None:
        first = self.registry.register(self.sample)
        second = self.registry.register(copy.deepcopy(self.sample))
        self.assertEqual(first, second)

    def test_same_version_cannot_be_replaced_in_place(self) -> None:
        self.registry.register(self.sample)
        changed = copy.deepcopy(self.sample)
        changed["metadata"]["description"] = "Changed metadata with same version."
        with self.assertRaises(DuplicateExtensionVersionError):
            self.registry.register(changed)

    def test_invalid_manifest_is_rejected_before_registration(self) -> None:
        changed = copy.deepcopy(self.sample)
        changed["permissions"]["requested"] = []
        del changed["metadata"]["license"]
        with self.assertRaises(ManifestValidationError):
            self.registry.register(changed)
        self.assertEqual(self.registry.list_extensions(), ())

    def test_invalid_transition_does_not_mutate_registry(self) -> None:
        record = self.registry.register(self.sample)
        with self.assertRaises(LifecycleTransitionError):
            self.registry.transition(record.key.extension_id, record.key.version, ExtensionState.ENABLED, actor="test", reason="skip gates")
        self.assertEqual(self.registry.get(record.key.extension_id, record.key.version).state, ExtensionState.DISCOVERED)
        self.assertEqual(self.registry.audit_events, ())

    def test_approval_is_required_before_approved_state(self) -> None:
        record = self.registry.register(self.sample)
        self.registry.transition(record.key.extension_id, record.key.version, ExtensionState.EVALUATING, actor="test", reason="begin review")
        with self.assertRaises(LifecycleTransitionError):
            self.registry.transition(record.key.extension_id, record.key.version, ExtensionState.APPROVED, actor="reviewer", reason="review")
        self.assertEqual(len(self.registry.audit_events), 1)

    def test_successful_transitions_create_audit_events(self) -> None:
        record = enabled_record(self.registry)
        self.assertEqual(record.state, ExtensionState.ENABLED)
        self.assertEqual(len(self.registry.audit_events), 6)
        self.assertEqual(self.registry.audit_events[1].approval_ref, "review:unit-test")
        self.assertTrue(all(event.actor and event.reason for event in self.registry.audit_events))


class CapabilityPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ExtensionRegistry()
        self.record = enabled_record(self.registry)
        self.now = datetime.now(timezone.utc)
        self.request = CapabilityRequest(
            key=self.record.key,
            principal_id="user:loofy",
            tenant_id="tenant:loofy",
            capability="repository.contents.read",
            resource_id="repo:Loofy147/Loofy-Extensions",
            environment="development",
        )
        self.grant = CapabilityGrant(
            grant_id="grant-001",
            key=self.record.key,
            principal_id=self.request.principal_id,
            tenant_id=self.request.tenant_id,
            capability=self.request.capability,
            resource_id=self.request.resource_id,
            environment=self.request.environment,
            granted_by="owner:loofy",
            expires_at=self.now + timedelta(hours=1),
        )

    def test_no_grant_means_deny(self) -> None:
        decision = authorize(self.record, self.request, (), now=self.now)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "no-matching-grant")

    def test_exact_unexpired_grant_allows_requested_read(self) -> None:
        decision = authorize(self.record, self.request, (self.grant,), now=self.now)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.grant_id, "grant-001")

    def test_resource_scope_is_exact(self) -> None:
        wrong_scope = replace(self.grant, resource_id="repo:someone/else")
        decision = authorize(self.record, self.request, (wrong_scope,), now=self.now)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "no-matching-grant")

    def test_tenant_scope_is_exact(self) -> None:
        other_tenant = replace(self.grant, tenant_id="tenant:someone-else")
        decision = authorize(self.record, self.request, (other_tenant,), now=self.now)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "no-matching-grant")

    def test_expired_grant_is_denied(self) -> None:
        expired = replace(self.grant, expires_at=self.now - timedelta(seconds=1))
        decision = authorize(self.record, self.request, (expired,), now=self.now)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "expired-or-unapproved-grant")

    def test_unrequested_permission_is_denied_even_if_granted(self) -> None:
        unrequested = replace(self.request, capability="deployment.execute")
        grant = replace(self.grant, capability="deployment.execute", approval_ref="approval:123")
        decision = authorize(self.record, unrequested, (grant,), now=self.now)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "capability-not-requested")

    def test_high_impact_capability_requires_approval_evidence(self) -> None:
        writer = replace(self.record, requested_permissions=frozenset({"deployment.execute"}))
        request = replace(self.request, key=writer.key, capability="deployment.execute")
        no_approval = replace(self.grant, key=writer.key, capability="deployment.execute", approval_ref=None)
        decision = authorize(writer, request, (no_approval,), now=self.now)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "expired-or-unapproved-grant")

        approved = replace(no_approval, approval_ref="approval:deploy-2026-01")
        decision = authorize(writer, request, (approved,), now=self.now)
        self.assertTrue(decision.allowed)


if __name__ == "__main__":
    unittest.main()
