# Phase 1 Contract Review

Status: reference contract hardened; CI evidence is required before the phase is marked complete.

This document describes the present in-memory contract. It does not imply production-ready persistence, identity verification, grant issuance, or extension execution.

## Lifecycle transition contract

| Current state | Allowed next states | Meaning |
| --- | --- | --- |
| discovered | evaluating, rejected | Candidate recorded; no trust implied |
| evaluating | approved, rejected, discovered | Review in progress, accepted, rejected, or returned to discovery |
| approved | installed, suspended | Approval recorded; install is still a separate operation |
| installed | configured, disabled, uninstalled | Metadata/runtime installation exists; no assumption that code ran |
| configured | validated, disabled, uninstalled | Configuration supplied; validation pending |
| validated | configured, enabled, suspended, disabled | Validation passed for the reviewed candidate |
| enabled | degraded, suspended, updating, disabled | Enabled state; runtime enforcement remains external |
| degraded | enabled, suspended, updating, disabled | Operational health is impaired |
| suspended | validated, disabled, uninstalled | Containment state; revalidation precedes re-enable |
| updating | enabled, validated, degraded, suspended | Update attempt resolved; validated can represent a rolled-back candidate being rechecked |
| disabled | approved, installed, uninstalled | Disabled candidate; re-entry still follows lifecycle gates |
| rejected | none | Terminal rejected record |
| uninstalled | none | Terminal uninstall record |

The reference module validates state transitions only. It does not install, update, suspend, revoke external tokens, cancel jobs, or execute extension code. A production orchestrator must perform those effects and reconcile its durable state with their outcomes.

## Capability risk classification

- Current policy identifier: `1.0.0` in `loofy_extensions.lifecycle.CAPABILITY_RISK_POLICY_VERSION`.
- The reference policy identifies explicit high-impact capabilities and uses conservative suffix/prefix rules.
- A policy change requires a version bump and regression tests.
- The classifier is not the sole authorization control. Production should use a reviewed capability catalogue with stable identifiers and risk labels.
- The operation receiving a request must authorize the actual actor, tenant, resource, environment, extension digest, capability and approval again immediately before any consequential side effect.

## Approval evidence

The in-memory lifecycle core requires an `approval_ref` for transition to `approved` and for enabling a manifest that requests a high-impact capability. A reference is only a pointer recorded in an audit event; presence does not prove validity or authority.

A future approval service must bind evidence to at least the actor, extension ID and immutable version/digest, capability, resource, environment, decision, timestamp and expiration. Approval must be checked by the consuming operation, not inferred from UI state or extension metadata.

## Grant contract

The current `CapabilityGrant` is a caller-supplied immutable value object. Authorization is default-deny and matches the extension version, principal, capability, resource, environment and unexpired grant exactly. Expiration is exclusive: a grant is denied when `expires_at <= now`. Naive timestamps are rejected.

Not implemented yet: trusted grant issuance, grantor authorization, durable revocation, tenant binding, a durable identity store, approval verification, and distributed consistency. These are production gates, not implicit capabilities.

## Identity and artifact provenance

The record carries distinct fields that must not be conflated:

- **Manifest digest:** SHA-256 of canonicalized manifest JSON; identifies the declared contract.
- **Artifact digest:** digest of the executable or distributable artifact, when present.
- **Source revision:** immutable revision identifier of the source repository, when present.
- **Publisher provenance:** authenticated evidence tying a publisher to an artifact/revision; not established by this reference core.

A matching manifest digest does not prove the referenced artifact has not changed, that the publisher is authentic, or that a declared license is compatible. Before executable extensions are permitted, require immutable artifact identity, verified source provenance, licensing and dependency evidence, and a staged update/rollback process.

## Phase 1 verification checklist

- [ ] State transition and update-recovery cases are covered by unit tests.
- [ ] Actor, reason, and timestamp invariants are tested.
- [ ] Capability risk policy version and representative high-/low-risk names are tested.
- [ ] Exact-expiry behavior and timezone-awareness checks are tested.
- [ ] Existing manifest schema validator and full unit suite pass in CI.
- [ ] A reviewer confirms that approval references remain evidence pointers—not authorization by themselves.

## Deliberately deferred

No database, durable event log, secret vault, GitHub write operation, webhook service, queue, arbitrary plugin loader, or production deployment is part of Phase 1.
