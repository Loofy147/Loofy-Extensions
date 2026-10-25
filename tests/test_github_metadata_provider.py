"""Contract tests for the read-only GitHub metadata adapter."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from loofy_extensions.providers import (
    GitHubHttpResponse,
    GitHubRepositoryMetadataProvider,
    ProviderError,
)


class FakeTransport:
    def __init__(self, response: GitHubHttpResponse) -> None:
        self.response = response
        self.urls: list[str] = []

    def get(self, url: str) -> GitHubHttpResponse:
        self.urls.append(url)
        return self.response


def repository_payload() -> dict[str, object]:
    return {
        "id": 1432761713,
        "full_name": "Loofy147/Loofy-Extensions",
        "description": "Governed extension foundation",
        "visibility": "public",
        "default_branch": "main",
        "private": False,
        "archived": False,
        "created_at": "2026-10-25T02:21:49Z",
        "updated_at": "2026-10-25T03:31:49Z",
        "html_url": "https://github.com/Loofy147/Loofy-Extensions",
        "url": "https://api.github.com/repos/Loofy147/Loofy-Extensions",
    }


class GitHubRepositoryMetadataProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fetched_at = datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc)
        self.transport = FakeTransport(
            GitHubHttpResponse(
                status_code=200,
                json_body=repository_payload(),
                headers={"ETag": '"repo-etag-v1"'},
            )
        )
        self.provider = GitHubRepositoryMetadataProvider(
            self.transport,
            clock=lambda: self.fetched_at,
        )

    def test_normalizes_metadata_and_preserves_provenance(self) -> None:
        result = self.provider.get_repository("Loofy147", "Loofy-Extensions")
        self.assertEqual(result.source_id, "1432761713")
        self.assertEqual(result.full_name, "Loofy147/Loofy-Extensions")
        self.assertEqual(result.visibility, "public")
        self.assertEqual(result.default_branch, "main")
        self.assertEqual(result.links.html, "https://github.com/Loofy147/Loofy-Extensions")
        self.assertEqual(result.links.api, "https://api.github.com/repos/Loofy147/Loofy-Extensions")
        self.assertEqual(result.updated_at, datetime(2026, 10, 25, 3, 31, 49, tzinfo=timezone.utc))
        self.assertEqual(result.provenance.source_updated_at, result.updated_at)
        self.assertEqual(result.provenance.retrieved_at, self.fetched_at)
        self.assertEqual(result.provenance.source_id, result.source_id)
        self.assertEqual(result.provenance.etag, '"repo-etag-v1"')
        self.assertEqual(result.provenance.operation, "repository.metadata.read")
        self.assertEqual(
            self.transport.urls,
            ["https://api.github.com/repos/Loofy147/Loofy-Extensions"],
        )

    def test_rejects_path_injection_before_transport(self) -> None:
        with self.assertRaises(ProviderError) as context:
            self.provider.get_repository("owner/other", "repo")
        self.assertEqual(context.exception.code, "invalid-identifier")
        self.assertEqual(self.transport.urls, [])

    def test_rejects_non_success_upstream_response_without_echoing_body(self) -> None:
        self.transport.response = GitHubHttpResponse(
            status_code=403,
            json_body={"message": "sensitive upstream details"},
            headers={},
        )
        with self.assertRaises(ProviderError) as context:
            self.provider.get_repository("Loofy147", "Loofy-Extensions")
        self.assertEqual(context.exception.code, "upstream-http-error")
        self.assertNotIn("sensitive upstream details", str(context.exception))

    def test_rejects_malformed_source_timestamp(self) -> None:
        payload = repository_payload()
        payload["updated_at"] = "yesterday"
        self.transport.response = GitHubHttpResponse(200, payload, {})
        with self.assertRaises(ProviderError) as context:
            self.provider.get_repository("Loofy147", "Loofy-Extensions")
        self.assertEqual(context.exception.code, "invalid-payload")

    def test_rejects_naive_provider_clock(self) -> None:
        provider = GitHubRepositoryMetadataProvider(
            self.transport,
            clock=lambda: datetime(2026, 10, 25, 4, 0),
        )
        with self.assertRaises(ProviderError) as context:
            provider.get_repository("Loofy147", "Loofy-Extensions")
        self.assertEqual(context.exception.code, "invalid-clock")

    def test_rejects_response_for_different_repository(self) -> None:
        payload = repository_payload()
        payload["full_name"] = "someone/other"
        self.transport.response = GitHubHttpResponse(200, payload, {})
        with self.assertRaises(ProviderError):
            self.provider.get_repository("Loofy147", "Loofy-Extensions")

    def test_rejects_untrusted_api_origin(self) -> None:
        with self.assertRaises(ValueError):
            GitHubRepositoryMetadataProvider(
                self.transport,
                api_base_url="https://api.github.com.attacker.invalid",
            )
        self.assertEqual(self.transport.urls, [])

    def test_rejects_untrusted_html_link(self) -> None:
        payload = repository_payload()
        payload["html_url"] = "https://github.com.attacker.invalid/Loofy147/Loofy-Extensions"
        self.transport.response = GitHubHttpResponse(200, payload, {})
        with self.assertRaises(ProviderError) as context:
            self.provider.get_repository("Loofy147", "Loofy-Extensions")
        self.assertEqual(context.exception.code, "invalid-payload")


if __name__ == "__main__":
    unittest.main()
