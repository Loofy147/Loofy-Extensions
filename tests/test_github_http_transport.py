"""Tests for the concrete, read-only GitHub.com HTTP transport."""

from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from loofy_extensions.providers import (
    GitHubRepositoryMetadataProvider,
    ProviderError,
    UrllibGitHubTransport,
)
from loofy_extensions.providers.github_http import _NoRedirect


class FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200, headers=None) -> None:
        self.status = status
        self.headers = headers or {}
        self.body = body
        self.read_sizes: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size=-1):
        self.read_sizes.append(size)
        if size is None or size < 0:
            return self.body
        return self.body[:size]


class FakeOpener:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        return self.result


def repository_payload() -> dict[str, object]:
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


class UrllibGitHubTransportTests(unittest.TestCase):
    def test_performs_get_with_host_supplied_token_and_verified_https_context(self) -> None:
        payload = repository_payload()
        body = json.dumps(payload).encode("utf-8")
        response = FakeResponse(body, headers={"ETag": '"fixture-etag"'})
        opener = FakeOpener(result=response)
        supplier_calls = []

        def token_supplier():
            supplier_calls.append(True)
            return "host-token-value"

        transport = UrllibGitHubTransport(
            token_supplier=token_supplier,
            timeout_seconds=3.5,
            max_response_bytes=4096,
        )
        with (
            patch("loofy_extensions.providers.github_http.urllib.request.build_opener", return_value=opener) as build_opener,
            patch("loofy_extensions.providers.github_http.ssl.create_default_context") as create_tls_context,
        ):
            result = transport.get("https://api.github.com/repos/owner/repo")

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json_body, payload)
        self.assertEqual(result.headers["ETag"], '"fixture-etag"')
        self.assertEqual(len(supplier_calls), 1)
        request = opener.requests[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, "https://api.github.com/repos/owner/repo")
        self.assertEqual(request.get_header("Authorization"), "Bearer host-token-value")
        self.assertEqual(request.get_header("Accept"), "application/vnd.github+json")
        self.assertEqual(request.get_header("X-github-api-version"), "2022-11-28")
        self.assertEqual(opener.timeouts, [3.5])
        self.assertEqual(response.read_sizes, [4097])
        create_tls_context.assert_called_once_with()
        self.assertEqual(build_opener.call_args.args[0].proxies, {})

    def test_no_token_supplier_sends_no_authorization_header(self) -> None:
        response = FakeResponse(json.dumps(repository_payload()).encode("utf-8"))
        opener = FakeOpener(result=response)
        transport = UrllibGitHubTransport()
        with patch("loofy_extensions.providers.github_http.urllib.request.build_opener", return_value=opener):
            transport.get("https://api.github.com/repos/owner/repo")
        self.assertIsNone(opener.requests[0].get_header("Authorization"))

    def test_calls_token_supplier_for_each_request_without_persisting_token(self) -> None:
        tokens = iter(("first-token", "second-token"))
        opener = FakeOpener(result=FakeResponse(json.dumps(repository_payload()).encode("utf-8")))
        transport = UrllibGitHubTransport(token_supplier=lambda: next(tokens))
        with patch("loofy_extensions.providers.github_http.urllib.request.build_opener", return_value=opener):
            transport.get("https://api.github.com/repos/owner/repo")
            transport.get("https://api.github.com/repos/owner/repo")
        self.assertEqual(
            [request.get_header("Authorization") for request in opener.requests],
            ["Bearer first-token", "Bearer second-token"],
        )

    def test_rejects_untrusted_origins_and_non_repository_paths_before_network(self) -> None:
        transport = UrllibGitHubTransport()
        invalid_urls = (
            "http://api.github.com/repos/owner/repo",
            "https://api.github.com.attacker.invalid/repos/owner/repo",
            "https://user@api.github.com/repos/owner/repo",
            "https://api.github.com:443/repos/owner/repo",
            "https://api.github.com/repos/owner/repo?redirect=https://attacker.invalid",
            "https://api.github.com/repos/owner/repo#fragment",
            "https://api.github.com/repos/owner/../other",
            "https://api.github.com/repos/owner%2Fattacker/repo",
            "https://api.github.com/contents/owner/repo",
        )
        with patch("loofy_extensions.providers.github_http.urllib.request.build_opener") as build_opener:
            for url in invalid_urls:
                with self.subTest(url=url), self.assertRaises(ProviderError) as context:
                    transport.get(url)
                self.assertEqual(context.exception.code, "invalid-url")
            build_opener.assert_not_called()

    def test_token_supplier_failure_is_sanitized_and_does_not_open_network(self) -> None:
        def broken_supplier():
            raise RuntimeError("secret token source internals")

        transport = UrllibGitHubTransport(token_supplier=broken_supplier)
        with patch("loofy_extensions.providers.github_http.urllib.request.build_opener") as build_opener:
            with self.assertRaises(ProviderError) as context:
                transport.get("https://api.github.com/repos/owner/repo")
        self.assertEqual(context.exception.code, "credential-unavailable")
        self.assertNotIn("secret token source internals", str(context.exception))
        build_opener.assert_not_called()

    def test_invalid_token_value_is_rejected(self) -> None:
        transport = UrllibGitHubTransport(token_supplier=lambda: "token\nwith-control")
        with patch("loofy_extensions.providers.github_http.urllib.request.build_opener") as build_opener:
            with self.assertRaises(ProviderError) as context:
                transport.get("https://api.github.com/repos/owner/repo")
        self.assertEqual(context.exception.code, "credential-unavailable")
        build_opener.assert_not_called()

    def test_transport_failure_is_sanitized(self) -> None:
        opener = FakeOpener(error=TimeoutError("secret upstream internals"))
        transport = UrllibGitHubTransport()
        with patch("loofy_extensions.providers.github_http.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ProviderError) as context:
                transport.get("https://api.github.com/repos/owner/repo")
        self.assertEqual(context.exception.code, "network-error")
        self.assertNotIn("secret upstream internals", str(context.exception))

    def test_http_error_returns_only_sanitized_status_envelope(self) -> None:
        error = urllib.error.HTTPError(
            "https://api.github.com/repos/owner/repo",
            403,
            "Forbidden",
            {"X-RateLimit-Remaining": "0"},
            io.BytesIO(b"secret response body"),
        )
        opener = FakeOpener(error=error)
        transport = UrllibGitHubTransport()
        with patch("loofy_extensions.providers.github_http.urllib.request.build_opener", return_value=opener):
            response = transport.get("https://api.github.com/repos/owner/repo")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json_body, {"message": "GitHub repository metadata request failed."})
        self.assertNotIn("secret response body", json.dumps(response.json_body))

    def test_redirect_is_not_followed(self) -> None:
        self.assertIsNone(
            _NoRedirect().redirect_request(
                request=None,
                response=None,
                code=302,
                message="Found",
                headers={"Location": "https://attacker.invalid/collect"},
                new_url="https://attacker.invalid/collect",
            )
        )

    def test_response_body_is_bounded(self) -> None:
        opener = FakeOpener(result=FakeResponse(b"x" * 17))
        transport = UrllibGitHubTransport(max_response_bytes=16)
        with patch("loofy_extensions.providers.github_http.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ProviderError) as context:
                transport.get("https://api.github.com/repos/owner/repo")
        self.assertEqual(context.exception.code, "response-too-large")
        self.assertEqual(opener.requests[0].get_method(), "GET")

    def test_invalid_json_and_non_object_json_are_rejected(self) -> None:
        invalid_payloads = (b"{not-json", b"[]", b'"string"')
        for body in invalid_payloads:
            with self.subTest(body=body):
                opener = FakeOpener(result=FakeResponse(body))
                transport = UrllibGitHubTransport()
                with patch("loofy_extensions.providers.github_http.urllib.request.build_opener", return_value=opener):
                    with self.assertRaises(ProviderError) as context:
                        transport.get("https://api.github.com/repos/owner/repo")
                self.assertEqual(context.exception.code, "invalid-payload")

    def test_provider_works_with_concrete_transport_without_real_network(self) -> None:
        payload = repository_payload()
        opener = FakeOpener(
            result=FakeResponse(
                json.dumps(payload).encode("utf-8"),
                headers={"ETag": '"provider-etag"'},
            )
        )
        transport = UrllibGitHubTransport()
        provider = GitHubRepositoryMetadataProvider(
            transport,
            clock=lambda: __import__("datetime").datetime(2026, 10, 25, tzinfo=__import__("datetime").timezone.utc),
        )
        with patch("loofy_extensions.providers.github_http.urllib.request.build_opener", return_value=opener):
            result = provider.get_repository("owner", "repo")
        self.assertEqual(result.source_id, "77")
        self.assertEqual(result.provenance.etag, '"provider-etag"')
        self.assertEqual(opener.requests[0].get_method(), "GET")

    def test_constructor_rejects_unbounded_or_invalid_settings(self) -> None:
        for options in (
            {"timeout_seconds": 0},
            {"timeout_seconds": float("inf")},
            {"timeout_seconds": True},
            {"max_response_bytes": 0},
            {"max_response_bytes": True},
            {"user_agent": "bad\nagent"},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                UrllibGitHubTransport(**options)


if __name__ == "__main__":
    unittest.main()
