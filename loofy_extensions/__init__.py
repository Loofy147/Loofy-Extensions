"""Reference core for the Loofy Extensions contract."""

from .lifecycle import LifecycleTransitionError, transition_record
from .models import AuditEvent, ExtensionKey, ExtensionRecord, ExtensionState
from .policy import CapabilityGrant, CapabilityRequest, PolicyDecision, authorize
from .grants import (
    GrantAuditEvent,
    GrantAuthority,
    GrantConflictError,
    GrantPolicyError,
    InMemoryGrantStore,
)
from .registry import (
    DuplicateExtensionVersionError,
    ExtensionRegistry,
    ManifestValidationError,
)
from .tasks import (
    ExecutionEnvelope,
    TaskExecutionError,
    TaskResult,
    TaskRunConflictError,
    TaskRunner,
)

__all__ = [
    "AuditEvent",
    "CapabilityGrant",
    "CapabilityRequest",
    "DuplicateExtensionVersionError",
    "ExtensionKey",
    "ExtensionRecord",
    "ExtensionRegistry",
    "ExtensionState",
    "ExecutionEnvelope",
    "GrantAuditEvent",
    "GrantAuthority",
    "GrantConflictError",
    "GrantPolicyError",
    "InMemoryGrantStore",
    "LifecycleTransitionError",
    "ManifestValidationError",
    "PolicyDecision",
    "TaskExecutionError",
    "TaskResult",
    "TaskRunConflictError",
    "TaskRunner",
    "authorize",
    "transition_record",
]
