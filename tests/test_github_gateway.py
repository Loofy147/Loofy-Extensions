"""Tests for tenant-scoped authorization at the provider operation boundary."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from dataclasses import replace

from loofy_extensions import CapabilityGrant, ExtensionRegistry, ExtensionState
from loofy_extensions.providers import (
    AuthorizationContextUnavailable,
    AuthorizedGitHubMetadataReader,
    CallerContext,
    GitHubHttpResponse,
    GitHubRepositoryMetadataProvider,
    InMemoryOperationAuditSink,
    OperationAuthorizationError,
    ProviderError,
)
from loofy_extensions.providers.github_gateway import CAPABILITY_REPOSITORY_METADATA_READ
from loofy_extensions.validation import DEFAULT_EXAMPLES


class FakeTransport:
    def __init__(self, response: GitHubHttpResponse) -> None:
        self.response = response
        self.urls: list[str] = []

    def get(self, url: str) -> GitHubHttpResponse:
        self.urls.append(url)
        return self.response


class FailingAuditSink:
    def append(self, event) -> None:
        raise OSError("audit unavailable")


def metadata_payload() -> dict[str, object]:
    return {
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
    }


def enabled_metadata_record(registry: ExtensionRegistry):
    manifest = json.loads(
        next(DEFAULT_EXAMPLES.rglob("extension.json")).read_text(encoding="utf-8")
    )
    manifest["permissions"]["requested"] = [CAPABILITY_REPOSITORY_METADATA_READ]
    manifest["capabilities"]["requires"] = [CAPABILITY_REPOSITORY_METADATA_READ]
    record = registry.register(manifest)
    for target, kwargs in (
        (ExtensionState.EVALUATING, {}),
        (ExtensionState.APPROVED, {"approval_ref": "review:gateway-test"}),
        (ExtensionState.INSTALLED, {}),
        (ExtensionState.CONFIGURED, {}),
        (ExtensionState.VALIDATED, {}),
        (ExtensionState.ENABLED, {}),
    ):
        record = registry.transition(
            record.key.extension_id,
            record.key.version,
            target,
            actor="test-operator",
            reason=f"gateway fixture -> {target.value}",
            **kwargs,
        )
    return record


class AuthorizedGitHubMetadataReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc)
        self.registry = ExtensionRegistry()
        self.record = enabled_metadata_record(self.registry)
        self.transport = FakeTransport(GitHubHttpResponse(200, metadata_payload(), {"ETag": '"fixture-etag"'}))
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
        self.resource_id = "github:repository:owner/repo"
        self.grant = CapabilityGrant(
            grant_id="grant-alpha",
            key=self.record.key,
            principal_id=self.caller.principal_id,
            tenant_id=self.caller.tenant_id,
            capability=CAPABILITY_REPOSITORY_METADATA_READ,
            resource_id=self.resource_id,
            environment=self.caller.environment,
            granted_by="owner:alice",
            expires_at=self.now + timedelta(hours=1),
        )

    def make_reader(self, grants=None, *, record_loader=None, audit_sink=None):
        return AuthorizedGitHubMetadataReader(
            self.provider,
            extension_key=self.record.key,
            record_loader=record_loader or (lambda: self.record),
            grants_loader=lambda: tuple(grants or ()),
            audit_sink=audit_sink or self.audit,
            clock=lambda: self.now,
        )

    def test_denied_read_is_audited_before_transport_is_called(self) -> None:
        reader = self.make_reader()
        with self.assertRaises(OperationAuthorizationError) as context:
            reader.read_repository("owner", "repo", caller=self.caller)
        self.assertEqual(context.exception.code, "no-matching-grant")
        self.assertEqual(self.transport.urls, [])
        self.assertEqual(len(self.audit.events), 1)
        self.assertEqual(self.audit.events[0].outcome, "denied")
        self.assertEqual(self.audit.events[0].tenant_id, "tenant:alpha")

    def test_grant_from_another_tenant_is_denied(self) -> None:
        other_tenant = replace(self.grant, tenant_id="tenant:beta")
        reader = self.make_reader((other_tenant,))
        with self.assertRaises(OperationAuthorizationError):
            reader.read_repository("owner", "repo", caller=self.caller)
        self.assertEqual(self.transport.urls, [])
        self.assertEqual(self.audit.events[0].decision_code, "no-matching-grant")

    def test_valid_grant_authorizes_and_audits_read_outcome(self) -> None:
        reader = self.make_reader((self.grant,))
        result = reader.read_repository("owner", "repo", caller=self.caller)
        self.assertEqual(result.source_id, "77")
        self.assertEqual(self.transport.urls, ["https://api.github.com/repos/owner/repo"])
        self.assertEqual([event.outcome for event in self.audit.events], ["authorized", "succeeded"])
        self.assertEqual(self.audit.events[-1].source_id, "77")
        self.assertEqual(self.audit.events[-1].manifest_digest, self.record.manifest_digest)

    def test_disabled_extension_is_denied_before_provider_call(self) -> None:
        disabled = replace(self.record, state=ExtensionState.DISABLED)
        reader = self.make_reader((self.grant,), record_loader=lambda: disabled)
        with self.assertRaises(OperationAuthorizationError) as context:
            reader.read_repository("owner", "repo", caller=self.caller)
        self.assertEqual(context.exception.code, "extension-not-enabled")
        self.assertEqual(self.transport.urls, [])

    def test_provider_failure_is_audited_and_propagated(self) -> None:
        self.transport.response = GitHubHttpResponse(503, {"message": "private detail"}, {})
        reader = self.make_reader((self.grant,))
        with self.assertRaises(ProviderError) as context:
            reader.read_repository("owner", "repo", caller=self.caller)
        self.assertEqual(context.exception.code, "upstream-http-error")
        self.assertEqual([event.outcome for event in self.audit.events], ["authorized", "provider-error"])
        self.assertNotIn("private detail", str(context.exception))

    def test_unavailable_policy_state_fails_closed(self) -> None:
        def unavailable():
            raise RuntimeError("secret internal details")

        reader = self.make_reader((self.grant,), record_loader=unavailable)
        with self.assertRaises(AuthorizationContextUnavailable):
            reader.read_repository("owner", "repo", caller=self.caller)
        self.assertEqual(self.transport.urls, [])
        self.assertEqual(self.audit.events[0].decision_code, "authorization-context-unavailable")

    def test_audit_failure_blocks_provider_call(self) -> None:
        reader = self.make_reader((self.grant,), audit_sink=FailingAuditSink())
        with self.assertRaises(OSError):
            reader.read_repository("owner", "repo", caller=self.caller)
        self.assertEqual(self.transport.urls, [])


if __name__ == "__main__":
    unittest.main()
