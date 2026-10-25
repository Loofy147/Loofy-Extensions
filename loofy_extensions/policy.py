"""Default-deny capability authorization for the reference core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .lifecycle import is_high_impact_capability
from .models import ExtensionKey, ExtensionRecord, ExtensionState, utc_now


@dataclass(frozen=True)
class CapabilityGrant:
    grant_id: str
    key: ExtensionKey
    principal_id: str
    capability: str
    resource_id: str
    environment: str
    granted_by: str
    expires_at: datetime
    approval_ref: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "grant_id",
            "principal_id",
            "capability",
            "resource_id",
            "environment",
            "granted_by",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} is required")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must be timezone-aware")


@dataclass(frozen=True)
class CapabilityRequest:
    key: ExtensionKey
    principal_id: str
    capability: str
    resource_id: str
    environment: str


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    code: str
    message: str
    grant_id: str | None = None


def authorize(
    record: ExtensionRecord,
    request: CapabilityRequest,
    grants: tuple[CapabilityGrant, ...] | list[CapabilityGrant],
    *,
    now: datetime | None = None,
) -> PolicyDecision:
    """Authorize only exact, unexpired grants for an enabled extension version.

    Wildcards and implicit grants are deliberately unsupported in this reference
    implementation. A production policy service must also bind grants to a tenant
    and enforce authorization again at the external operation boundary.
    """
    if request.key != record.key:
        return PolicyDecision(False, "extension-version-mismatch", "Request version does not match record.")
    if record.state != ExtensionState.ENABLED:
        return PolicyDecision(False, "extension-not-enabled", "Extension is not enabled.")
    if request.capability not in record.requested_permissions:
        return PolicyDecision(False, "capability-not-requested", "Manifest did not request this permission.")

    current_time = now or utc_now()
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    matching = [
        grant
        for grant in grants
        if grant.key == request.key
        and grant.principal_id == request.principal_id
        and grant.capability == request.capability
        and grant.resource_id == request.resource_id
        and grant.environment == request.environment
    ]
    if not matching:
        return PolicyDecision(False, "no-matching-grant", "No grant matches the principal, capability, resource and environment.")

    matching.sort(key=lambda grant: (grant.expires_at, grant.grant_id))
    for grant in matching:
        if grant.expires_at <= current_time:
            continue
        if is_high_impact_capability(request.capability) and not grant.approval_ref:
            continue
        return PolicyDecision(True, "authorized", "A valid scoped grant matched.", grant.grant_id)

    return PolicyDecision(False, "expired-or-unapproved-grant", "Matching grants are expired or lack required approval evidence.")
