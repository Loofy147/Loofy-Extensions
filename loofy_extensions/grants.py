"""In-memory grant issuance and revocation reference services.

These classes are useful for policy tests and prototyping only. A production
implementation must replace the store with transactional persistence and wire
the authorizer callbacks to authenticated identity and tenant membership data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Callable
from uuid import uuid4

from .lifecycle import is_high_impact_capability
from .models import ExtensionKey, ExtensionRecord, ExtensionState
from .policy import CapabilityGrant


class GrantPolicyError(PermissionError):
    """Stable denial from a grant issuance or revocation request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class GrantConflictError(ValueError):
    """Raised when an immutable grant ID is reused for different grant content."""


@dataclass(frozen=True)
class GrantAuditEvent:
    event_type: str
    grant_id: str
    actor_id: str
    principal_id: str
    tenant_id: str
    extension_id: str
    extension_version: str
    capability: str
    resource_id: str
    environment: str
    reason: str
    occurred_at: datetime


@dataclass(frozen=True)
class _StoredGrant:
    grant: CapabilityGrant
    revoked_at: datetime | None = None


class InMemoryGrantStore:
    """Thread-safe process-local grant store; state disappears at restart."""

    def __init__(self) -> None:
        self._grants: dict[str, _StoredGrant] = {}
        self._events: list[GrantAuditEvent] = []
        self._lock = RLock()

    @property
    def audit_events(self) -> tuple[GrantAuditEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def active_grants(self) -> tuple[CapabilityGrant, ...]:
        """Return all unrevoked grants; authorization still checks expiry."""
        with self._lock:
            return tuple(
                stored.grant
                for _, stored in sorted(self._grants.items())
                if stored.revoked_at is None
            )

    def get(self, grant_id: str) -> CapabilityGrant:
        with self._lock:
            try:
                return self._grants[grant_id].grant
            except KeyError as exc:
                raise GrantPolicyError("grant-not-found", "The requested grant does not exist.") from exc

    def is_revoked(self, grant_id: str) -> bool:
        with self._lock:
            try:
                return self._grants[grant_id].revoked_at is not None
            except KeyError as exc:
                raise GrantPolicyError("grant-not-found", "The requested grant does not exist.") from exc

    def issue(self, grant: CapabilityGrant, *, reason: str, occurred_at: datetime) -> CapabilityGrant:
        """Insert a grant once; identical retries are idempotent."""
        if not reason.strip():
            raise ValueError("reason is required")
        self._require_aware(occurred_at, "occurred_at")
        with self._lock:
            existing = self._grants.get(grant.grant_id)
            if existing is not None:
                if existing.grant != grant:
                    raise GrantConflictError("grant ID already exists with different immutable content")
                if existing.revoked_at is not None:
                    raise GrantPolicyError("grant-id-revoked", "A revoked grant ID cannot be reissued.")
                return existing.grant

            self._grants[grant.grant_id] = _StoredGrant(grant=grant)
            self._events.append(self._event("issued", grant, grant.granted_by, reason, occurred_at))
            return grant

    def revoke(
        self,
        grant_id: str,
        *,
        actor_id: str,
        reason: str,
        occurred_at: datetime,
    ) -> CapabilityGrant:
        """Revoke a grant atomically; repeated revocation is rejected."""
        if not actor_id.strip():
            raise ValueError("actor_id is required")
        if not reason.strip():
            raise ValueError("reason is required")
        self._require_aware(occurred_at, "occurred_at")
        with self._lock:
            stored = self._grants.get(grant_id)
            if stored is None:
                raise GrantPolicyError("grant-not-found", "The requested grant does not exist.")
            if stored.revoked_at is not None:
                raise GrantPolicyError("grant-already-revoked", "The grant is already revoked.")
            self._grants[grant_id] = _StoredGrant(stored.grant, revoked_at=occurred_at)
            self._events.append(self._event("revoked", stored.grant, actor_id, reason, occurred_at))
            return stored.grant

    @staticmethod
    def _require_aware(value: datetime, field_name: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")

    @staticmethod
    def _event(
        event_type: str,
        grant: CapabilityGrant,
        actor_id: str,
        reason: str,
        occurred_at: datetime,
    ) -> GrantAuditEvent:
        return GrantAuditEvent(
            event_type=event_type,
            grant_id=grant.grant_id,
            actor_id=actor_id,
            principal_id=grant.principal_id,
            tenant_id=grant.tenant_id,
            extension_id=grant.key.extension_id,
            extension_version=grant.key.version,
            capability=grant.capability,
            resource_id=grant.resource_id,
            environment=grant.environment,
            reason=reason.strip(),
            occurred_at=occurred_at.astimezone(timezone.utc),
        )


class GrantAuthority:
    """Validates grant issuance and revocation against trusted host callbacks."""

    def __init__(
        self,
        store: InMemoryGrantStore,
        *,
        record_loader: Callable[[ExtensionKey], ExtensionRecord],
        tenant_member_verifier: Callable[[str, str], bool],
        grant_scope_authorizer: Callable[[str, str, str, str, str], bool],
        clock: Callable[[], datetime] | None = None,
        grant_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._record_loader = record_loader
        self._tenant_member_verifier = tenant_member_verifier
        self._grant_scope_authorizer = grant_scope_authorizer
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._grant_id_factory = grant_id_factory or (lambda: uuid4().hex)

    def issue_grant(
        self,
        *,
        key: ExtensionKey,
        principal_id: str,
        tenant_id: str,
        capability: str,
        resource_id: str,
        environment: str,
        actor_id: str,
        reason: str,
        expires_at: datetime,
        approval_ref: str | None = None,
    ) -> CapabilityGrant:
        self._require_nonblank(
            principal_id=principal_id,
            tenant_id=tenant_id,
            capability=capability,
            resource_id=resource_id,
            environment=environment,
            actor_id=actor_id,
            reason=reason,
        )
        now = self._now()
        if not isinstance(expires_at, datetime) or expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise GrantPolicyError("invalid-expiry", "Grant expiry must be a timezone-aware datetime.")
        if expires_at <= now:
            raise GrantPolicyError("invalid-expiry", "Grant expiry must be in the future.")

        try:
            record = self._record_loader(key)
        except Exception:
            raise GrantPolicyError("extension-unavailable", "Trusted extension state is unavailable.") from None
        if not isinstance(record, ExtensionRecord):
            raise GrantPolicyError("extension-unavailable", "Trusted extension state is invalid.")
        if record.key != key:
            raise GrantPolicyError("extension-version-mismatch", "Loaded extension version does not match the requested key.")
        if record.state != ExtensionState.ENABLED:
            raise GrantPolicyError("extension-not-enabled", "A grant can only be issued to an enabled extension version.")
        if capability not in record.requested_permissions:
            raise GrantPolicyError("capability-not-requested", "The extension manifest did not request this capability.")

        try:
            principal_is_member = self._tenant_member_verifier(principal_id, tenant_id)
            actor_is_member = self._tenant_member_verifier(actor_id, tenant_id)
        except Exception:
            raise GrantPolicyError("membership-check-failed", "Tenant membership could not be verified.") from None
        if not principal_is_member:
            raise GrantPolicyError("principal-not-tenant-member", "The principal is not a verified member of the tenant.")
        if not actor_is_member:
            raise GrantPolicyError("actor-not-tenant-member", "The grant issuer is not a verified member of the tenant.")

        try:
            can_grant = self._grant_scope_authorizer(
                actor_id, tenant_id, capability, resource_id, environment
            )
        except Exception:
            raise GrantPolicyError("grant-authority-unavailable", "Granting authority could not be verified.") from None
        if not can_grant:
            raise GrantPolicyError("grant-not-authorized", "The actor cannot grant this capability for the requested scope.")

        if is_high_impact_capability(capability) and (
            not isinstance(approval_ref, str) or not approval_ref.strip()
        ):
            raise GrantPolicyError("approval-required", "High-impact capabilities require approval evidence.")

        grant_id = self._grant_id_factory()
        if not isinstance(grant_id, str) or not grant_id.strip():
            raise GrantPolicyError("invalid-grant-id", "Grant ID factory returned an invalid identifier.")
        grant = CapabilityGrant(
            grant_id=grant_id,
            key=key,
            principal_id=principal_id,
            tenant_id=tenant_id,
            capability=capability,
            resource_id=resource_id,
            environment=environment,
            granted_by=actor_id,
            expires_at=expires_at,
            approval_ref=approval_ref,
        )
        try:
            return self._store.issue(grant, reason=reason, occurred_at=now)
        except GrantConflictError:
            raise GrantPolicyError("grant-id-conflict", "A grant with this ID already exists.") from None

    def revoke_grant(self, *, grant_id: str, actor_id: str, reason: str) -> CapabilityGrant:
        self._require_nonblank(grant_id=grant_id, actor_id=actor_id, reason=reason)
        try:
            grant = self._store.get(grant_id)
            revoked = self._store.is_revoked(grant_id)
        except GrantPolicyError:
            raise
        if revoked:
            raise GrantPolicyError("grant-already-revoked", "The grant is already revoked.")

        try:
            actor_is_member = self._tenant_member_verifier(actor_id, grant.tenant_id)
        except Exception:
            raise GrantPolicyError("membership-check-failed", "Tenant membership could not be verified.") from None
        if not actor_is_member:
            raise GrantPolicyError("actor-not-tenant-member", "The revocation actor is not a verified member of the tenant.")

        try:
            can_revoke = self._grant_scope_authorizer(
                actor_id,
                grant.tenant_id,
                grant.capability,
                grant.resource_id,
                grant.environment,
            )
        except Exception:
            raise GrantPolicyError("grant-authority-unavailable", "Revocation authority could not be verified.") from None
        if not can_revoke:
            raise GrantPolicyError("revoke-not-authorized", "The actor cannot revoke this grant.")

        try:
            return self._store.revoke(
                grant_id,
                actor_id=actor_id,
                reason=reason,
                occurred_at=self._now(),
            )
        except GrantPolicyError:
            raise

    def _now(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise GrantPolicyError("invalid-clock", "Grant authority clock must be timezone-aware.")
        return timestamp.astimezone(timezone.utc)

    @staticmethod
    def _require_nonblank(**values: str) -> None:
        for field_name, value in values.items():
            if not isinstance(value, str) or not value.strip():
                raise GrantPolicyError("invalid-input", f"{field_name} is required.")
