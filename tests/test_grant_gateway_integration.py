"""End-to-end reference tests for grant issuance, use, revocation, and disablement.

All outbound requests use an in-memory fake transport. These tests never contact
GitHub and do not perform external writes.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from loofy_extensions import (
    ExtensionRegistry,
    ExtensionState,
    GrantAuthority,
    InMemoryGrantStore,
)
from loofy_extensions.providers import (
    AuthorizedGitHubMetadataReader,
    CallerContext,
    GitHubHttpResponse,
    GitHubRepositoryMetadataProvider,
    InMemoryOperationAuditSink,
    OperationAuthorizationError,
)
from loofy_extensions.providers.github_gateway import CAPABILITY_REPOSITORY_METADATA_READ
from loofy_extensions.validation import DEFAULT_EXAMPLES


class FakeTransport:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str) -> GitHubHttpResponse:
        self.urls.append(url)
        return GitHubHttpResponse(
            status_code=200,
            json_body={
                "id": 77,
                "full_name": "owner/repo",
                "description": "fixture",
                "visibility": "public",
                "default_branch": "main",
                "private": False,
                "archived": False,
                "created_at": "2026-10-01T00:00:00Z",
                "updated_at": "2026-10-20T00:00:00Z",
                "html_url": "https://github.com/owner/repo",
                "url": "https://api.github.com/repos/owner/repo",
            },
            headers={"ETag": '"fixture-etag"'},
        )


class GrantGatewayIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc)
        self.registry = ExtensionRegistry()
        manifest = json.loads(
            next(DEFAULT_EXAMPLES.rglob("extension.json")).read_text(encoding="utf-8")
        )
        manifest["permissions"]["requested"] = [CAPABILITY_REPOSITORY_METADATA_READ]
        manifest["capabilities"]["requires"] = [CAPABILITY_REPOSITORY_METADATA_READ]
        candidate = self.registry.register(manifest)
        for target, kwargs in (
            (ExtensionState.EVALUATING, {}),
            (ExtensionState.APPROVED, {"approval_ref": "review:integration-test"}),
            (ExtensionState.INSTALLED, {}),
            (ExtensionState.CONFIGURED, {}),
            (ExtensionState.VALIDATED, {}),
            (ExtensionState.ENABLED, {}),
        ):
            candidate = self.registry.transition(
                candidate.key.extension_id,
                candidate.key.version,
                target,
                actor="test-operator",
                reason=f"integration fixture: {target.value}",
                **kwargs,
            )
        self.key = candidate.key
        self.store = InMemoryGrantStore()
        self.grant_authority = GrantAuthority(
            self.store,
            record_loader=lambda key: self.registry.get(key.extension_id, key.version),
            tenant_member_verifier=lambda principal, tenant:
                principal in {"user:alice", "owner:alice"} and tenant == "tenant:alpha",
            grant_scope_authorizer=lambda actor, tenant, capability, resource, environment:
                actor == "owner:alice"
                and tenant == "tenant:alpha"
                and capability == CAPABILITY_REPOSITORY_METADATA_READ
                and resource == "github:repository:owner/repo"
                and environment == "test",
            clock=lambda: self.now,
            grant_id_factory=self.next_grant_id,
        )
        self.grant_ids = iter(("integration-grant-1", "integration-grant-2"))
        self.transport = FakeTransport()
        self.provider = GitHubRepositoryMetadataProvider(
            self.transport,
            clock=lambda: self.now,
        )
        self.audit = InMemoryOperationAuditSink()
        self.caller = CallerContext(
            principal_id="user:alice",
            tenant_id="tenant:alpha",
            environment="test",
        )
        self.reader = AuthorizedGitHubMetadataReader(
            self.provider,
            extension_key=self.key,
            record_loader=lambda: self.registry.get(self.key.extension_id, self.key.version),
            grants_loader=self.store.active_grants,
            audit_sink=self.audit,
            clock=lambda: self.now,
        )

    def next_grant_id(self) -> str:
        return next(self.grant_ids)

    def issue_read_grant(self):
        return self.grant_authority.issue_grant(
            key=self.key,
            principal_id=self.caller.principal_id,
            tenant_id=self.caller.tenant_id,
            capability=CAPABILITY_REPOSITORY_METADATA_READ,
            resource_id="github:repository:owner/repo",
            environment=self.caller.environment,
            actor_id="owner:alice",
            reason="authorize read-only metadata integration test",
            expires_at=self.now + timedelta(hours=1),
        )

    def test_issued_grant_authorizes_read_then_revocation_denies_next_read(self) -> None:
        grant = self.issue_read_grant()
        first_result = self.reader.read_repository("owner", "repo", caller=self.caller)
        self.assertEqual(first_result.source_id, "77")
        self.assertEqual(len(self.transport.urls), 1)
        self.assertEqual(self.audit.events[-1].outcome, "succeeded")

        self.grant_authority.revoke_grant(
            grant_id=grant.grant_id,
            actor_id="owner:alice",
            reason="revoke after positive control",
        )
        with self.assertRaises(OperationAuthorizationError) as context:
            self.reader.read_repository("owner", "repo", caller=self.caller)
        self.assertEqual(context.exception.code, "no-matching-grant")
        self.assertEqual(len(self.transport.urls), 1)
        self.assertEqual(self.audit.events[-1].outcome, "denied")
        self.assertEqual(self.audit.events[-1].decision_code, "no-matching-grant")

    def test_disabled_extension_denies_read_even_with_active_grant(self) -> None:
        grant = self.issue_read_grant()
        self.registry.transition(
            self.key.extension_id,
            self.key.version,
            ExtensionState.DISABLED,
            actor="operator",
            reason="disable extension for integration test",
        )
        with self.assertRaises(OperationAuthorizationError) as context:
            self.reader.read_repository("owner", "repo", caller=self.caller)
        self.assertEqual(context.exception.code, "extension-not-enabled")
        self.assertEqual(self.store.active_grants(), (grant,))
        self.assertEqual(self.transport.urls, [])
        self.assertEqual(self.audit.events[-1].outcome, "denied")


if __name__ == "__main__":
    unittest.main()
