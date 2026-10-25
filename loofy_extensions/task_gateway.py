"""Host authorization and operation-audit boundary for manifest validation tasks.

The wrapper receives trusted caller context and a host-supplied authorization
callback. It never accepts actor/tenant identity from the task envelope and
emits audit records before and after the allowlisted built-in task.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Protocol, Sequence

from .models import ExtensionKey, ExtensionRecord
from .policy import CapabilityGrant, CapabilityRequest, PolicyDecision, authorize as authorize_capability
from .providers.github_gateway import OperationAuditEvent, OperationAuditSink
from .tasks import ExecutionEnvelope, TaskExecutionError, TaskResult, TaskRunner


TASK_RUNNER_EXTENSION_ID = "com.loofy.extensions.task-runner"
TASK_RUNNER_EXTENSION_VERSION = "1.0.0"
TASK_CAPABILITY_PREFIX = "task."


class TaskAuthorizationError(PermissionError):
    """Raised when task authorization is denied or cannot be safely resolved."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TaskAuthorizationContextUnavailable(TaskAuthorizationError):
    """Raised when the host authorization callback fails; task execution is denied."""


@dataclass(frozen=True)
class TaskCallerContext:
    """Identity context constructed by the host authentication layer."""

    principal_id: str
    tenant_id: str
    environment: str

    def __post_init__(self) -> None:
        for field_name in ("principal_id", "tenant_id", "environment"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value.strip()) > 256
                or any(ord(character) < 32 for character in value)
            ):
                raise ValueError(f"{field_name} must be a valid non-empty string of at most 256 characters")


@dataclass(frozen=True)
class TaskAuthorizationDecision:
    """Decision returned by a host-supplied task authorization policy."""

    allowed: bool
    code: str
    message: str


class TaskAuthorizer(Protocol):
    """Trusted host callback for task, principal, tenant, resource and environment."""

    def authorize(
        self,
        *,
        principal_id: str,
        tenant_id: str,
        task_id: str,
        resource_id: str,
        environment: str,
    ) -> TaskAuthorizationDecision:
        """Return an explicit allow or deny decision."""


class CapabilityTaskAuthorizer:
    """Bridge task requests to the existing tenant-scoped capability policy.

    The injected record and grant loaders must provide current authoritative
    state. Caller identity is provided by AuthorizedTaskRunner after the host
    authentication layer has constructed TaskCallerContext; this adapter does
    not authenticate users or issue grants.
    """

    _TASK_CAPABILITIES = {
        "manifest.validate": "task.manifest.validate",
    }

    def __init__(
        self,
        *,
        extension_key: ExtensionKey,
        record_loader: Callable[[ExtensionKey], ExtensionRecord],
        grants_loader: Callable[[], Sequence[CapabilityGrant]],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(extension_key, ExtensionKey):
            raise ValueError("extension_key must be an ExtensionKey")
        self._extension_key = extension_key
        self._record_loader = record_loader
        self._grants_loader = grants_loader
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def authorize(
        self,
        *,
        principal_id: str,
        tenant_id: str,
        task_id: str,
        resource_id: str,
        environment: str,
    ) -> TaskAuthorizationDecision:
        capability = self._TASK_CAPABILITIES.get(task_id)
        if capability is None:
            return TaskAuthorizationDecision(
                False,
                "unsupported-task",
                "No capability mapping exists for the requested task.",
            )

        # Loader errors propagate to AuthorizedTaskRunner, which records a
        # stable fail-closed authorization-context-unavailable outcome.
        record = self._record_loader(self._extension_key)
        if not isinstance(record, ExtensionRecord) or record.key != self._extension_key:
            raise ValueError("The task extension record is unavailable or mismatched.")
        grants = tuple(self._grants_loader())
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Task authorization clock must return a timezone-aware datetime.")

        request = CapabilityRequest(
            key=self._extension_key,
            principal_id=principal_id,
            tenant_id=tenant_id,
            capability=capability,
            resource_id=resource_id,
            environment=environment,
        )
        decision: PolicyDecision = authorize_capability(
            record,
            request,
            grants,
            now=now.astimezone(timezone.utc),
        )
        return TaskAuthorizationDecision(
            allowed=decision.allowed,
            code=decision.code,
            message=decision.message,
        )


class AuthorizedTaskRunner:
    """Authorize and audit before running the built-in validation task.

    Actor, tenant and environment are overwritten from the trusted caller
    context. Values supplied in those fields of the task envelope are not used
    for authorization or attribution. The host callback must make its decision
    using current identity and policy state. The sink is called before task
    execution; a failed pre-run audit append prevents task execution.
    """

    def __init__(
        self,
        runner: TaskRunner,
        *,
        authorizer: TaskAuthorizer,
        audit_sink: OperationAuditSink,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._runner = runner
        self._authorizer = authorizer
        self._audit_sink = audit_sink
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        envelope: ExecutionEnvelope,
        *,
        caller: TaskCallerContext,
    ) -> TaskResult:
        if not isinstance(envelope, ExecutionEnvelope):
            raise TaskExecutionError("invalid-envelope", "A typed ExecutionEnvelope is required.")
        if not isinstance(caller, TaskCallerContext):
            raise TaskAuthorizationError(
                "invalid-caller-context",
                "Caller context must be constructed by the trusted host.",
            )

        run_id = self._required_id(envelope.run_id, "run_id", maximum=128)
        task_id = self._required_id(envelope.task_id, "task_id", maximum=128)
        resource_id = self._required_id(envelope.resource_id, "resource_id", maximum=512)
        if task_id not in self._runner.supported_tasks:
            self._emit(
                envelope=envelope,
                caller=caller,
                task_id=task_id,
                resource_id=resource_id,
                outcome="denied",
                decision_code="unsupported-task",
                occurred_at=self._now(),
                correlation_id=run_id,
            )
            raise TaskAuthorizationError(
                "unsupported-task",
                "The requested task is not in the host-owned allowlist.",
            )

        authorized_envelope = replace(
            envelope,
            run_id=run_id,
            task_id=task_id,
            actor_id=caller.principal_id,
            tenant_id=caller.tenant_id,
            resource_id=resource_id,
            environment=caller.environment,
        )
        try:
            decision = self._authorizer.authorize(
                principal_id=caller.principal_id,
                tenant_id=caller.tenant_id,
                task_id=task_id,
                resource_id=resource_id,
                environment=caller.environment,
            )
        except Exception:
            self._emit(
                envelope=authorized_envelope,
                caller=caller,
                task_id=task_id,
                resource_id=resource_id,
                outcome="denied",
                decision_code="authorization-context-unavailable",
                occurred_at=self._now(),
                correlation_id=run_id,
            )
            raise TaskAuthorizationContextUnavailable(
                "authorization-context-unavailable",
                "Trusted task authorization is unavailable; task request denied.",
            ) from None

        if (
            not isinstance(decision, TaskAuthorizationDecision)
            or not isinstance(decision.allowed, bool)
            or not isinstance(decision.code, str)
            or not decision.code.strip()
            or len(decision.code.strip()) > 128
            or any(ord(character) < 32 for character in decision.code)
            or not isinstance(decision.message, str)
        ):
            self._emit(
                envelope=authorized_envelope,
                caller=caller,
                task_id=task_id,
                resource_id=resource_id,
                outcome="denied",
                decision_code="invalid-authorization-decision",
                occurred_at=self._now(),
                correlation_id=run_id,
            )
            raise TaskAuthorizationContextUnavailable(
                "invalid-authorization-decision",
                "Task authorization did not return a valid decision; task request denied.",
            )

        if not decision.allowed:
            denial_code = self._required_id(decision.code, "decision.code", maximum=128)
            self._emit(
                envelope=authorized_envelope,
                caller=caller,
                task_id=task_id,
                resource_id=resource_id,
                outcome="denied",
                decision_code=denial_code,
                occurred_at=self._now(),
                correlation_id=run_id,
            )
            raise TaskAuthorizationError(denial_code, decision.message or "Task request denied.")

        # If this append fails, no task code is invoked.
        self._emit(
            envelope=authorized_envelope,
            caller=caller,
            task_id=task_id,
            resource_id=resource_id,
            outcome="authorized",
            decision_code=self._required_id(decision.code, "decision.code", maximum=128),
            occurred_at=self._now(),
            correlation_id=run_id,
        )
        try:
            result = self._runner.run(authorized_envelope)
        except TaskExecutionError as exc:
            self._emit(
                envelope=authorized_envelope,
                caller=caller,
                task_id=task_id,
                resource_id=resource_id,
                outcome="task-error",
                decision_code=exc.code,
                occurred_at=self._now(),
                correlation_id=run_id,
            )
            raise
        except Exception:
            # Record a stable code only; never leak internal exception details.
            self._emit(
                envelope=authorized_envelope,
                caller=caller,
                task_id=task_id,
                resource_id=resource_id,
                outcome="task-error",
                decision_code="task-runtime-error",
                occurred_at=self._now(),
                correlation_id=run_id,
            )
            raise

        self._emit(
            envelope=authorized_envelope,
            caller=caller,
            task_id=task_id,
            resource_id=resource_id,
            outcome="succeeded" if result.valid else "validation_failed",
            decision_code="ok" if result.valid else "manifest-schema-invalid",
            occurred_at=self._now(),
            correlation_id=run_id,
            input_digest=result.input_digest,
            source_id=result.target_extension_id,
        )
        return result

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("task audit clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _required_id(value: object, field: str, *, maximum: int) -> str:
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > maximum
            or any(ord(character) < 32 for character in value)
        ):
            raise TaskExecutionError(
                "invalid-envelope",
                f"{field} must be a non-empty string no longer than {maximum} characters.",
            )
        return value.strip()

    def _emit(
        self,
        *,
        envelope: ExecutionEnvelope,
        caller: TaskCallerContext,
        task_id: str,
        resource_id: str,
        outcome: str,
        decision_code: str,
        occurred_at: datetime,
        correlation_id: str,
        input_digest: str = "unavailable",
        source_id: str | None = None,
    ) -> None:
        self._audit_sink.append(
            OperationAuditEvent(
                event_type=f"task.{task_id}",
                extension_id=TASK_RUNNER_EXTENSION_ID,
                extension_version=TASK_RUNNER_EXTENSION_VERSION,
                manifest_digest=input_digest,
                principal_id=caller.principal_id,
                tenant_id=caller.tenant_id,
                capability=f"{TASK_CAPABILITY_PREFIX}{task_id}",
                resource_id=resource_id,
                environment=caller.environment,
                outcome=outcome,
                decision_code=decision_code,
                occurred_at=occurred_at,
                source_id=source_id,
                correlation_id=correlation_id,
            )
        )
