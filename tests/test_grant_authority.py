"""Tests for in-memory grant issuance/revocation authority."""

from __future__ import annotations

import copy
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from loofy_extensions import ExtensionKey, ExtensionRegistry, ExtensionState
from loofy_extensions.grants import (
    GrantAuthority,
    GrantConflictError,
    GrantPolicyError,
    InMemoryGrantStore,
)
from loofy_extensions.validation import DEFAULT_EXAMPLES


def enabled_record(registry: ExtensionRegistry):
    manifest = json.loads(
        next(DEFAULT_EXAMPLES.rglob("extension.json")).read_text(encoding="utf-8")
    )
    manifest["permissions"]["requested"] = ["repository.contents.read"]
    manifest["capabilities"]["requires"] = ["repository.contents.read"]
    record = registry.register(manifest)
    for target, kwargs in (
        (ExtensionState.EVALUATING, {}),
        (ExtensionState.APPROVED, {"approval_ref": "review:grant-tests"}),
        (ExtensionState.INSTALLED, {}),
        (ExtensionState.CONFIGURED, {}),
        (ExtensionState.VALIDATED, {}),
        (ExtensionState.ENABLED, {}),
    ):
        record = registry.transition(
            record.key.extension_id,
            record.key.version,
            target,
            actor="fixture",
            reason=f"fixture transition: {target.value}",
            **kwargs,
        )
    return record


class GrantAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc)
        self.registry = ExtensionRegistry()
        self.record = enabled_record(self.registry)
        self.store = InMemoryGrantStore()
        self.next_grant_id = "grant-fixed-001"
        self.authority = self.make_authority()

    def make_authority(
        self,
        *,
        record_loader=None,
        tenant_member_verifier=None,
        grant_scope_authorizer=None,
        store=None,
    ) -> GrantAuthority:
        return GrantAuthority(
            store or self.store,
            record_loader=record_loader or (
                lambda key: self.record if key == self.record.key else self.fail_record()
            ),
            tenant_member_verifier=tenant_member_verifier or (
                lambda principal, tenant: principal == "user:alice" and tenant == "tenant:alpha"
            ),
            grant_scope_authorizer=grant_scope_authorizer or (
                lambda actor, tenant, capability, resource, environment:
                    actor == "owner:alice"
                    and tenant == "tenant:alpha"
                    and resource == "repo:owner/name"
                    and environment == "test"
                    and capability.startswith("repository.")
            ),
            clock=lambda: self.now,
            grant_id_factory=lambda: self.next_grant_id,
        )

    @staticmethod
    def fail_record():
        raise KeyError("record missing")

    def issue(self, **overrides):
        args = {
            "key": self.record.key,
            "principal_id": "user:alice",
            "tenant_id": "tenant:alpha",
            "capability": "repository.contents.read",
            "resource_id": "repo:owner/name",
            "environment": "test",
            "actor_id": "owner:alice",
            "reason": "approve read-only metadata access",
            "expires_at": self.now + timedelta(hours=1),
        }
        args.update(overrides)
        return self.authority.issue_grant(**args)

    def test_issues_exact_scoped_grant_and_audit_event(self) -> None:
        grant = self.issue()
        self.assertEqual(grant.grant_id, self.next_grant_id)
        self.assertEqual(grant.tenant_id, "tenant:alpha")
        self.assertEqual(grant.principal_id, "user:alice")
        self.assertEqual(grant.capability, "repository.contents.read")
        self.assertEqual(self.store.active_grants(), (grant,))
        self.assertEqual(len(self.store.audit_events), 1)
        self.assertEqual(self.store.audit_events[0].event_type, "issued")
        self.assertEqual(self.store.audit_events[0].actor_id, "owner:alice")

    def test_rejects_principal_without_verified_tenant_membership(self) -> None:
        with self.assertRaises(GrantPolicyError) as context:
            self.issue(principal_id="user:outsider")
        self.assertEqual(context.exception.code, "principal-not-tenant-member")
        self.assertEqual(self.store.active_grants(), ())

    def test_rejects_actor_without_grant_scope_authority(self) -> None:
        with self.assertRaises(GrantPolicyError) as context:
            self.issue(actor_id="user:alice")
        self.assertEqual(context.exception.code, "grant-not-authorized")
        self.assertEqual(self.store.active_grants(), ())

    def test_rejects_capability_not_requested_by_manifest(self) -> None:
        with self.assertRaises(GrantPolicyError) as context:
            self.issue(capability="repository.contents.write")
        self.assertEqual(context.exception.code, "capability-not-requested")

    def test_rejects_expired_grant(self) -> None:
        with self.assertRaises(GrantPolicyError) as context:
            self.issue(expires_at=self.now)
        self.assertEqual(context.exception.code, "invalid-expiry")

    def test_rejects_naive_expiry(self) -> None:
        with self.assertRaises(GrantPolicyError) as context:
            self.issue(expires_at=datetime(2026, 10, 26, 4, 0))
        self.assertEqual(context.exception.code, "invalid-expiry")

    def test_high_impact_grant_requires_approval_pointer(self) -> None:
        writer_record = replace(
            self.record,
            requested_permissions=frozenset({"deployment.execute"}),
        )
        authority = self.make_authority(record_loader=lambda key: writer_record)
        with self.assertRaises(GrantPolicyError) as context:
            authority.issue_grant(
                key=writer_record.key,
                principal_id="user:alice",
                tenant_id="tenant:alpha",
                capability="deployment.execute",
                resource_id="repo:owner/name",
                environment="test",
                actor_id="owner:alice",
                reason="test high-impact gate",
                expires_at=self.now + timedelta(hours=1),
            )
        self.assertEqual(context.exception.code, "approval-required")

    def test_record_loader_failure_fails_closed(self) -> None:
        authority = self.make_authority(record_loader=self.fail_record)
        with self.assertRaises(GrantPolicyError) as context:
            authority.issue_grant(
                key=self.record.key,
                principal_id="user:alice",
                tenant_id="tenant:alpha",
                capability="repository.contents.read",
                resource_id="repo:owner/name",
                environment="test",
                actor_id="owner:alice",
                reason="test failure",
                expires_at=self.now + timedelta(hours=1),
            )
        self.assertEqual(context.exception.code, "extension-unavailable")
        self.assertEqual(self.store.active_grants(), ())

    def test_disabled_extension_cannot_receive_grant(self) -> None:
        disabled = replace(self.record, state=ExtensionState.DISABLED)
        authority = self.make_authority(record_loader=lambda key: disabled)
        with self.assertRaises(GrantPolicyError) as context:
            authority.issue_grant(
                key=disabled.key,
                principal_id="user:alice",
                tenant_id="tenant:alpha",
                capability="repository.contents.read",
                resource_id="repo:owner/name",
                environment="test",
                actor_id="owner:alice",
                reason="test disabled state",
                expires_at=self.now + timedelta(hours=1),
            )
        self.assertEqual(context.exception.code, "extension-not-enabled")

    def test_revocation_removes_grant_from_active_set_and_is_audited(self) -> None:
        grant = self.issue()
        revoked = self.authority.revoke_grant(
            grant_id=grant.grant_id,
            actor_id="owner:alice",
            reason="access no longer required",
        )
        self.assertEqual(revoked, grant)
        self.assertEqual(self.store.active_grants(), ())
        self.assertTrue(self.store.is_revoked(grant.grant_id))
        self.assertEqual(
            [event.event_type for event in self.store.audit_events],
            ["issued", "revoked"],
        )
        self.assertEqual(self.store.audit_events[-1].tenant_id, "tenant:alpha")

    def test_repeated_revocation_is_rejected(self) -> None:
        grant = self.issue()
        self.authority.revoke_grant(
            grant_id=grant.grant_id,
            actor_id="owner:alice",
            reason="revoke once",
        )
        with self.assertRaises(GrantPolicyError) as context:
            self.authority.revoke_grant(
                grant_id=grant.grant_id,
                actor_id="owner:alice",
                reason="revoke twice",
            )
        self.assertEqual(context.exception.code, "grant-already-revoked")

    def test_unauthorized_actor_cannot_revoke(self) -> None:
        grant = self.issue()
        with self.assertRaises(GrantPolicyError) as context:
            self.authority.revoke_grant(
                grant_id=grant.grant_id,
                actor_id="user:alice",
                reason="unauthorized revoke attempt",
            )
        self.assertEqual(context.exception.code, "revoke-not-authorized")
        self.assertEqual(self.store.active_grants(), (grant,))

    def test_store_rejects_mutation_under_same_grant_id(self) -> None:
        grant = self.issue()
        changed = replace(grant, resource_id="repo:another/repo")
        with self.assertRaises(GrantConflictError):
            self.store.issue(changed, reason="mutated grant", occurred_at=self.now)
        self.assertEqual(self.store.active_grants(), (grant,))

    def test_store_issue_retry_is_idempotent(self) -> None:
        grant = self.issue()
        duplicate = self.store.issue(grant, reason="safe retry", occurred_at=self.now)
        self.assertEqual(duplicate, grant)
        self.assertEqual(len(self.store.audit_events), 1)


if __name__ == "__main__":
    unittest.main()
