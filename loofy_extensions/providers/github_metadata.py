"""Read-only GitHub repository metadata adapter.

The adapter deliberately delegates HTTP/authentication to a host-supplied
transport. It has no token storage, write methods, retries, or side effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import quote, urlsplit


class ProviderError(RuntimeError):
    """Stable, non-secret-bearing error raised by the metadata provider."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GitHubHttpResponse:
    """Minimal response envelope supplied by a host-owned HTTP transport."""

    status_code: int
    json_body: Mapping[str, Any]
    headers: Mapping[str, str]


class ReadOnlyGitHubTransport(Protocol):
    """Transport contract: implement this using HTTP GET only."""

    def get(self, url: str) -> GitHubHttpResponse:
        """Fetch one JSON response from an approved GitHub API URL."""


@dataclass(frozen=True)
class RepositoryLinks:
    html: str
    api: str


@dataclass(frozen=True)
class RepositoryProvenance:
    provider: str
    operation: str
    source_uri: str
    source_id: str
    retrieved_at: datetime
    source_updated_at: datetime
    etag: str | None


@dataclass(frozen=True)
class GitHubRepositoryMetadata:
    source_id: str
    full_name: str
    description: str | None
    visibility: str
    default_branch: str
    private: bool
    archived: bool
    created_at: datetime
    updated_at: datetime
    links: RepositoryLinks
    provenance: RepositoryProvenance


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ProviderError("invalid-payload", f"GitHub response field {field!r} must be an ISO-8601 timestamp.")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ProviderError("invalid-payload", f"GitHub response field {field!r} is not a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProviderError("invalid-payload", f"GitHub response field {field!r} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _required_string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ProviderError("invalid-payload", f"GitHub response field {field!r} must be a non-empty string.")
    return value


class GitHubRepositoryMetadataProvider:
    """Retrieve and normalize metadata for one repository; never writes to GitHub.

    The current adapter targets GitHub.com only. Authentication, timeouts, TLS
    and transport-level retries belong to the injected transport. Credentials
    must not be stored in extension manifests or returned metadata.
    """

    provider_id = "github"
    operation_id = "repository.metadata.read"

    def __init__(
        self,
        transport: ReadOnlyGitHubTransport,
        *,
        api_base_url: str = "https://api.github.com",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        base = api_base_url.rstrip("/")
        parsed_base = urlsplit(base)
        if (
            parsed_base.scheme != "https"
            or parsed_base.hostname != "api.github.com"
            or parsed_base.username is not None
            or parsed_base.password is not None
            or parsed_base.port is not None
            or parsed_base.path not in ("",)
            or parsed_base.query
            or parsed_base.fragment
        ):
            raise ValueError("api_base_url must be the canonical https://api.github.com origin")
        self._transport = transport
        self._api_base_url = base
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_repository(self, owner: str, repository: str) -> GitHubRepositoryMetadata:
        """Read repository metadata with exact path validation and provenance."""
        if not self._valid_segment(owner, allow_dots=False):
            raise ProviderError("invalid-identifier", "GitHub owner must be a single valid path segment.")
        if not self._valid_segment(repository, allow_dots=True):
            raise ProviderError("invalid-identifier", "GitHub repository must be a single valid path segment.")

        url = (
            f"{self._api_base_url}/repos/"
            f"{quote(owner, safe='')}/{quote(repository, safe='')}"
        )
        response = self._transport.get(url)
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderError(
                "upstream-http-error",
                f"GitHub repository metadata request failed with HTTP {response.status_code}.",
            )
        payload = response.json_body
        if not isinstance(payload, Mapping):
            raise ProviderError("invalid-payload", "GitHub repository response must be a JSON object.")

        raw_id = payload.get("id")
        if isinstance(raw_id, bool) or not isinstance(raw_id, (int, str)) or not str(raw_id).strip():
            raise ProviderError("invalid-payload", "GitHub response field 'id' must be an integer or non-empty string.")
        full_name = _required_string(payload, "full_name")
        if full_name.casefold() != f"{owner}/{repository}".casefold():
            raise ProviderError("invalid-payload", "GitHub response repository identity does not match the requested resource.")
        default_branch = _required_string(payload, "default_branch")
        html_url = _required_string(payload, "html_url")
        api_url = _required_string(payload, "url")
        html_link = urlsplit(html_url)
        api_link = urlsplit(api_url)
        expected_path = f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}"
        if (
            html_link.scheme != "https"
            or html_link.hostname != "github.com"
            or html_link.path.rstrip("/") != f"/{quote(owner, safe='')}/{quote(repository, safe='')}"
            or html_link.query
            or html_link.fragment
            or api_link.scheme != "https"
            or api_link.hostname != "api.github.com"
            or api_link.path.rstrip("/") != expected_path
            or api_link.query
            or api_link.fragment
        ):
            raise ProviderError("invalid-payload", "GitHub repository links do not match the requested trusted resource.")
        if not isinstance(payload.get("private"), bool):
            raise ProviderError("invalid-payload", "GitHub response field 'private' must be a boolean.")
        if not isinstance(payload.get("archived"), bool):
            raise ProviderError("invalid-payload", "GitHub response field 'archived' must be a boolean.")
        description = payload.get("description")
        if description is not None and not isinstance(description, str):
            raise ProviderError("invalid-payload", "GitHub response field 'description' must be a string or null.")
        visibility = payload.get("visibility")
        if visibility is None:
            visibility = "private" if payload["private"] else "public"
        if not isinstance(visibility, str) or not visibility.strip():
            raise ProviderError("invalid-payload", "GitHub response field 'visibility' must be a non-empty string.")

        source_created_at = _parse_timestamp(payload.get("created_at"), "created_at")
        source_updated_at = _parse_timestamp(payload.get("updated_at"), "updated_at")
        retrieved_at = self._clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ProviderError("invalid-clock", "Provider clock must return a timezone-aware timestamp.")
        retrieved_at = retrieved_at.astimezone(timezone.utc)
        etag = next(
            (value for key, value in response.headers.items() if key.lower() == "etag"),
            None,
        )
        source_id = str(raw_id)
        provenance = RepositoryProvenance(
            provider=self.provider_id,
            operation=self.operation_id,
            source_uri=url,
            source_id=source_id,
            retrieved_at=retrieved_at,
            source_updated_at=source_updated_at,
            etag=etag,
        )
        return GitHubRepositoryMetadata(
            source_id=source_id,
            full_name=full_name,
            description=description,
            visibility=visibility,
            default_branch=default_branch,
            private=payload["private"],
            archived=payload["archived"],
            created_at=source_created_at,
            updated_at=source_updated_at,
            links=RepositoryLinks(html=html_url, api=api_url),
            provenance=provenance,
        )

    @staticmethod
    def _valid_segment(value: str, *, allow_dots: bool) -> bool:
        if not isinstance(value, str) or not value or value in {".", ".."}:
            return False
        if "/" in value or "\\" in value or any(ord(character) < 32 for character in value):
            return False
        pattern = r"[A-Za-z0-9_.-]+" if allow_dots else r"[A-Za-z0-9-]+"
        return re.fullmatch(pattern, value) is not None
