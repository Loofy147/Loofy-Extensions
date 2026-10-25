"""Explicit lifecycle transitions; this module never executes extension code."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .models import AuditEvent, ExtensionRecord, ExtensionState, utc_now


class LifecycleTransitionError(ValueError):
    """Raised when a requested extension lifecycle transition is not allowed."""


# Change this version and update the policy regression tests whenever the risk
# classification contract changes. This heuristic is a reference policy, not an
# authorization service or a substitute for operation-boundary enforcement.
CAPABILITY_RISK_POLICY_VERSION = "1.0.0"
HIGH_IMPACT_CAPABILITIES = frozenset(
    {
        "pull_request.merge",
        "repository.delete",
        "secret.rotate",
        "deployment.execute",
        "finance.transfer",
    }
)
HIGH_IMPACT_SUFFIXES = (".write", ".delete", ".execute", ".merge", ".rotate")
HIGH_IMPACT_PREFIXES = ("deployment.", "secret.rotate.", "finance.transfer.")


ALLOWED_TRANSITIONS: dict[ExtensionState, frozenset[ExtensionState]] = {
    ExtensionState.DISCOVERED: frozenset(
        {ExtensionState.EVALUATING, ExtensionState.REJECTED}
    ),
    ExtensionState.EVALUATING: frozenset(
        {ExtensionState.APPROVED, ExtensionState.REJECTED, ExtensionState.DISCOVERED}
    ),
    ExtensionState.APPROVED: frozenset(
        {ExtensionState.INSTALLED, ExtensionState.SUSPENDED}
    ),
    ExtensionState.INSTALLED: frozenset(
        {ExtensionState.CONFIGURED, ExtensionState.DISABLED, ExtensionState.UNINSTALLED}
    ),
    ExtensionState.CONFIGURED: frozenset(
        {ExtensionState.VALIDATED, ExtensionState.DISABLED, ExtensionState.UNINSTALLED}
    ),
    ExtensionState.VALIDATED: frozenset(
        {
            ExtensionState.CONFIGURED,
            ExtensionState.ENABLED,
            ExtensionState.SUSPENDED,
            ExtensionState.DISABLED,
        }
    ),
    ExtensionState.ENABLED: frozenset(
        {
            ExtensionState.DEGRADED,
            ExtensionState.SUSPENDED,
            ExtensionState.UPDATING,
            ExtensionState.DISABLED,
        }
    ),
    ExtensionState.DEGRADED: frozenset(
        {
            ExtensionState.ENABLED,
            ExtensionState.SUSPENDED,
            ExtensionState.UPDATING,
            ExtensionState.DISABLED,
        }
    ),
    ExtensionState.SUSPENDED: frozenset(
        {ExtensionState.VALIDATED, ExtensionState.DISABLED, ExtensionState.UNINSTALLED}
    ),
    # UPDATING may resolve to the prior enabled state, a degraded/suspended
    # containment state, or VALIDATED after a candidate is rolled back/rechecked.
    # It never means that an update has been installed or executed by this module.
    ExtensionState.UPDATING: frozenset(
        {
            ExtensionState.ENABLED,
            ExtensionState.VALIDATED,
            ExtensionState.DEGRADED,
            ExtensionState.SUSPENDED,
        }
    ),
    ExtensionState.DISABLED: frozenset(
        {ExtensionState.APPROVED, ExtensionState.INSTALLED, ExtensionState.UNINSTALLED}
    ),
    ExtensionState.REJECTED: frozenset(),
    ExtensionState.UNINSTALLED: frozenset(),
}


def is_high_impact_capability(capability: str) -> bool:
    """Classify capabilities that can create consequential external side effects.

    This policy is intentionally conservative and versioned. Capability names are
    untrusted input: production policy must use a reviewed capability catalogue
    and re-authorize the real operation at the external service boundary.
    """
    return (
        capability in HIGH_IMPACT_CAPABILITIES
        or capability.endswith(HIGH_IMPACT_SUFFIXES)
        or capability.startswith(HIGH_IMPACT_PREFIXES)
    )


def transition_record(
    record: ExtensionRecord,
    target: ExtensionState,
    *,
    actor: str,
    reason: str,
    approval_ref: str | None = None,
    occurred_at: datetime | None = None,
) -> tuple[ExtensionRecord, AuditEvent]:
    """Return a new record and audit event if the requested transition is valid.

    Approval references are recorded as evidence pointers only. This reference
    implementation checks their presence for gated transitions; it does not
    resolve, authenticate, or cryptographically bind them to a principal,
    manifest digest, scope, action, or expiration.
    """
    if not actor.strip():
        raise LifecycleTransitionError("actor is required for every transition")
    if not reason.strip():
        raise LifecycleTransitionError("reason is required for every transition")
    if target == record.state:
        raise LifecycleTransitionError(f"extension is already {target.value}")
    if target not in ALLOWED_TRANSITIONS[record.state]:
        raise LifecycleTransitionError(
            f"transition {record.state.value} -> {target.value} is not allowed"
        )
    if target == ExtensionState.APPROVED and not approval_ref:
        raise LifecycleTransitionError("approval_ref is required before approval")
    needs_enable_approval = (
        target == ExtensionState.ENABLED
        and any(is_high_impact_capability(cap) for cap in record.requested_permissions)
    )
    if needs_enable_approval and not approval_ref:
        raise LifecycleTransitionError(
            "approval_ref is required to enable an extension requesting high-impact capabilities"
        )

    timestamp = occurred_at or utc_now()
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise LifecycleTransitionError("occurred_at must be timezone-aware")

    updated = replace(record, state=target, updated_at=timestamp)
    event = AuditEvent(
        key=record.key,
        from_state=record.state,
        to_state=target,
        actor=actor.strip(),
        reason=reason.strip(),
        approval_ref=approval_ref,
        occurred_at=timestamp,
    )
    return updated, event
