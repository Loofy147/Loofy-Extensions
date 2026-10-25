"""Host-side authorization and audit boundary for repository metadata reads.

This service does not implement authentication or durable storage. Its context,
record loader, grant loader and audit sink must be supplied by the trusted host.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Callable, Protocol, Sequence
from uuid import uuid4

from ..models import ExtensionKey, ExtensionRecord
from ..policy import CapabilityGrant, CapabilityRequest, PolicyDecision, authorize
from .github_metadata import GitHubRepositoryMetadata, GitHubRepositoryMetadataProvider, ProviderError


CAPABILITY_REPOSITORY_METADATA_READ = "repository.metadata.read"


class OperationAuthorizationError(PermissionError):
    """Raised when a repository read is denied at the host operation boundary."""

    def __init__(self, decision: PolicyDecision) -> None:
        super().__init__(decision.message)
        self.code = decision.code
        self.decision = decision


class AuthorizationContextUnavailable(RuntimeError):
    """Raised when trusted host policy state cannot be loaded; fails closed."""


@dataclass(frozen=True)
class CallerContext:
    """Identity context resolved by the host authentication layer."""

    principal_id: str
    tenant_id: str
    environment: str

    def __post_init__(self) -> None:
        for field_name in ("principal_id", "tenant_id", "environment"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} is required")


@dataclass(frozen=True)
class OperationAuditEvent:
    event_type: str
    extension_id: str
    extension_version: str
    manifest_digest: str
    principal_id: str
    tenant_id: str
    capability: str
    resource_id: str
    environment: str
    outcome: str
    decision_code: str
    occurred_at: datetime
    source_id: str | None = None
    correlation_id: str = ""


class OperationAuditSink(Protocol):
    """Host-owned audit interface. Production implementations should be durable."""

    def append(self, event: OperationAuditEvent) -> None:
        """Persist or record an audit event before returning."""


class InMemoryOperationAuditSink:
    """Thread-safe test/development sink; not durable or production suitable."""

    def __init__(self) -> None:
        self._events: list[OperationAuditEvent] = []
        self._lock = RLock()

    def append(self, event: OperationAuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    @property
    def events(self) -> tuple[OperationAuditEvent, ...]:
        with self._lock:
            return tuple(self._events)


class AuthorizedGitHubMetadataReader:
    """Authorize, audit and then perform a read-only repository metadata request.

    The record and grant loaders must read trusted, current policy state. The
    caller context must come from host authentication, not user-supplied form
    fields. The audit sink is called before the outbound request; if that call
    fails, no provider request is made.
    """

    def __init__(
        self,
        provider: GitHubRepositoryMetadataProvider,
        *,
        extension_key: ExtensionKey,
        record_loader: Callable[[], ExtensionRecord],
        grants_loader: Callable[[], Sequence[CapabilityGrant]],
        audit_sink: OperationAuditSink,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._extension_key = extension_key
        self._record_loader = record_loader
        self._grants_loader = grants_loader
        self._audit_sink = audit_sink
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def read_repository(
        self,
        owner: str,
        repository: str,
        *,
        caller: CallerContext,
    ) -> GitHubRepositoryMetadata:
        resource_id = f"github:repository:{owner.casefold()}/{repository.casefold()}"
        correlation_id = uuid4().hex
        now = self._now()
        try:
            record = self._record_loader()
            grants = tuple(self._grants_loader())
        except Exception:
            self._emit_without_record(
                caller=caller,
                resource_id=resource_id,
                outcome="denied",
                decision_code="authorization-context-unavailable",
                occurred_at=now,
                correlation_id=correlation_id,
            )
            raise AuthorizationContextUnavailable(
                "Trusted extension or grant state is unavailable; request denied."
            ) from None

        request = CapabilityRequest(
            key=self._extension_key,
            principal_id=caller.principal_id,
            tenant_id=caller.tenant_id,
            capability=CAPABILITY_REPOSITORY_METADATA_READ,
            resource_id=resource_id,
            environment=caller.environment,
        )
        decision = authorize(record, request, grants, now=now)
        if not decision.allowed:
            self._emit(
                record=record,
                caller=caller,
                resource_id=resource_id,
                outcome="denied",
                decision_code=decision.code,
                occurred_at=now,
                correlation_id=correlation_id,
            )
            raise OperationAuthorizationError(decision)

        # Fail closed if the audit boundary cannot record the authorization decision.
        self._emit(
            record=record,
            caller=caller,
            resource_id=resource_id,
            outcome="authorized",
            decision_code=decision.code,
            occurred_at=now,
            correlation_id=correlation_id,
        )
        try:
            result = self._provider.get_repository(owner, repository)
        except ProviderError as exc:
            self._emit(
                record=record,
                caller=caller,
                resource_id=resource_id,
                outcome="provider-error",
                decision_code=exc.code,
                occurred_at=self._now(),
                correlation_id=correlation_id,
            )
            raise

        self._emit(
            record=record,
            caller=caller,
            resource_id=resource_id,
            outcome="succeeded",
            decision_code="ok",
            occurred_at=self._now(),
            source_id=result.source_id,
            correlation_id=correlation_id,
        )
        return result

    def _now(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("operation audit clock must return a timezone-aware timestamp")
        return timestamp.astimezone(timezone.utc)

    def _emit(
        self,
        *,
        record: ExtensionRecord,
        caller: CallerContext,
        resource_id: str,
        outcome: str,
        decision_code: str,
        occurred_at: datetime,
        correlation_id: str,
        source_id: str | None = None,
    ) -> None:
        self._audit_sink.append(
            OperationAuditEvent(
                event_type="repository.metadata.read",
                extension_id=record.key.extension_id,
                extension_version=record.key.version,
                manifest_digest=record.manifest_digest,
                principal_id=caller.principal_id,
                tenant_id=caller.tenant_id,
                capability=CAPABILITY_REPOSITORY_METADATA_READ,
                resource_id=resource_id,
                environment=caller.environment,
                outcome=outcome,
                decision_code=decision_code,
                occurred_at=occurred_at,
                source_id=source_id,
                correlation_id=correlation_id,
            )
        )

    def _emit_without_record(
        self,
        *,
        caller: CallerContext,
        resource_id: str,
        outcome: str,
        decision_code: str,
        occurred_at: datetime,
        correlation_id: str,
    ) -> None:
        self._audit_sink.append(
            OperationAuditEvent(
                event_type="repository.metadata.read",
                extension_id=self._extension_key.extension_id,
                extension_version=self._extension_key.version,
                manifest_digest="unavailable",
                principal_id=caller.principal_id,
                tenant_id=caller.tenant_id,
                capability=CAPABILITY_REPOSITORY_METADATA_READ,
                resource_id=resource_id,
                environment=caller.environment,
                outcome=outcome,
                decision_code=decision_code,
                occurred_at=occurred_at,
                correlation_id=correlation_id,
            )
        )
