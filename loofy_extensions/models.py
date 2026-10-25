"""Immutable value objects shared by the reference registry and policy core."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


class ExtensionState(str, Enum):
    DISCOVERED = "discovered"
    EVALUATING = "evaluating"
    APPROVED = "approved"
    INSTALLED = "installed"
    CONFIGURED = "configured"
    VALIDATED = "validated"
    ENABLED = "enabled"
    DEGRADED = "degraded"
    SUSPENDED = "suspended"
    UPDATING = "updating"
    DISABLED = "disabled"
    REJECTED = "rejected"
    UNINSTALLED = "uninstalled"


@dataclass(frozen=True, order=True)
class ExtensionKey:
    """Stable identity is extension ID plus immutable extension version."""

    extension_id: str
    version: str


@dataclass(frozen=True)
class ExtensionRecord:
    key: ExtensionKey
    name: str
    publisher: str
    source: str
    license: str
    kind: str
    manifest_digest: str
    artifact_digest: str | None
    source_revision: str | None
    requested_permissions: frozenset[str]
    provided_capabilities: frozenset[str]
    required_capabilities: frozenset[str]
    state: ExtensionState = ExtensionState.DISCOVERED
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class AuditEvent:
    key: ExtensionKey
    from_state: ExtensionState
    to_state: ExtensionState
    actor: str
    reason: str
    approval_ref: str | None
    occurred_at: datetime = field(default_factory=utc_now)
