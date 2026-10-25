"""Concrete GET-only GitHub.com HTTP transport.

The transport is deliberately narrow: canonical repository-metadata paths only,
TLS verification enabled, redirects disabled, bounded response bodies, and no
credential persistence. A host may inject a token supplier backed by its secret
system; the supplier is called for each request.
"""

from __future__ import annotations

import json
import math
import re
import socket
import ssl
import urllib.error
import urllib.request
from typing import Callable, Mapping
from urllib.parse import urlsplit

from .github_metadata import GitHubHttpResponse, ProviderError


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects, especially not across an authorization boundary."""

    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


class UrllibGitHubTransport:
    """A real, read-only GitHub.com transport using the Python standard library.

    Only GET requests for canonical /repos/{owner}/{repo} paths are allowed.
    A token supplier is optional for public repository metadata and is never
    cached by this instance. Network and decoding errors are converted to stable
    messages that do not include the URL response body, token, or exception text.
    """

    API_ORIGIN = "https://api.github.com"
    _REPOSITORY_PATH = re.compile(
        r"^/repos/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+$"
    )

    def __init__(
        self,
        *,
        token_supplier: Callable[[], str | None] | None = None,
        timeout_seconds: float = 5.0,
        max_response_bytes: int = 1_048_576,
        user_agent: str = "Loofy-Extensions/1.0",
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive finite number")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes < 1
        ):
            raise ValueError("max_response_bytes must be a positive integer")
        if (
            not isinstance(user_agent, str)
            or not user_agent.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in user_agent)
        ):
            raise ValueError("user_agent must be a non-empty string without control characters")
        if token_supplier is not None and not callable(token_supplier):
            raise ValueError("token_supplier must be callable")

        self._token_supplier = token_supplier
        self._timeout_seconds = float(timeout_seconds)
        self._max_response_bytes = max_response_bytes
        self._user_agent = user_agent.strip()

    def get(self, url: str) -> GitHubHttpResponse:
        """Perform one GET request to a canonical GitHub repository endpoint."""
        self._validate_url(url)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": self._user_agent,
        }

        if self._token_supplier is not None:
            try:
                token = self._token_supplier()
            except Exception:
                raise ProviderError(
                    "credential-unavailable",
                    "GitHub credentials could not be obtained from the host.",
                ) from None
            if token is not None:
                if (
                    not isinstance(token, str)
                    or not token.strip()
                    or any(ord(character) < 33 or ord(character) == 127 for character in token)
                ):
                    raise ProviderError(
                        "credential-unavailable",
                        "The host credential supplier returned an invalid credential.",
                    )
                headers["Authorization"] = f"Bearer {token.strip()}"

        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                urllib.request.HTTPSHandler(context=ssl.create_default_context()),
                _NoRedirect(),
            )
            with opener.open(request, timeout=self._timeout_seconds) as response:
                status_code = int(response.status if hasattr(response, "status") else response.getcode())
                response_headers = dict(response.headers.items())
                body = response.read(self._max_response_bytes + 1)
        except urllib.error.HTTPError as error:
            # HTTPError represents a non-success status (including blocked redirects).
            # Never read or forward its body; it may contain sensitive upstream data.
            return GitHubHttpResponse(
                status_code=int(error.code),
                json_body={"message": "GitHub repository metadata request failed."},
                headers=dict(error.headers.items()) if error.headers is not None else {},
            )
        except (urllib.error.URLError, TimeoutError, socket.timeout, ssl.SSLError, OSError):
            raise ProviderError(
                "network-error",
                "GitHub repository metadata request failed during transport.",
            ) from None
        except Exception:
            # Do not surface arbitrary transport exceptions to callers or audit logs.
            raise ProviderError(
                "network-error",
                "GitHub repository metadata request failed during transport.",
            ) from None

        if len(body) > self._max_response_bytes:
            raise ProviderError(
                "response-too-large",
                "GitHub repository metadata response exceeded the configured size limit.",
            )
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise ProviderError(
                "invalid-payload",
                "GitHub repository metadata response was not valid JSON.",
            ) from None
        if not isinstance(payload, Mapping):
            raise ProviderError(
                "invalid-payload",
                "GitHub repository metadata response must be a JSON object.",
            )
        return GitHubHttpResponse(
            status_code=status_code,
            json_body=payload,
            headers=response_headers,
        )

    @classmethod
    def _validate_url(cls, url: str) -> None:
        if not isinstance(url, str) or not url:
            raise ProviderError("invalid-url", "GitHub request URL is required.")
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            raise ProviderError("invalid-url", "GitHub request URL is malformed.") from None
        if (
            parsed.scheme != "https"
            or parsed.hostname != "api.github.com"
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
            or parsed.path in ("/", "")
            or cls._REPOSITORY_PATH.fullmatch(parsed.path) is None
            or any(segment in {".", ".."} for segment in parsed.path.split("/"))
            or "%" in parsed.path
            or any(ord(character) < 32 or ord(character) == 127 for character in url)
        ):
            raise ProviderError(
                "invalid-url",
                "Only canonical HTTPS GitHub repository metadata URLs are permitted.",
            )


__all__ = ["UrllibGitHubTransport"]
