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
    TaskResultStore,
    TaskRunConflictError,
    TaskRunner,
)
from .persistence import (
    CURRENT_SCHEMA_VERSION,
    ImmutableVersionConflictError,
    SQLiteStore,
    SchemaVersionError,
    StorageClosedError,
    StorageError,
)
from .task_gateway import (
    AuthorizedTaskRunner,
    CapabilityTaskAuthorizer,
    TaskAuthorizationContextUnavailable,
    TaskAuthorizationDecision,
    TaskAuthorizationError,
    TaskAuthorizer,
    TaskCallerContext,
)

__all__ = [
    "AuditEvent",
    "AuthorizedTaskRunner",
    "CapabilityGrant",
    "CapabilityRequest",
    "CapabilityTaskAuthorizer",
    "CURRENT_SCHEMA_VERSION",
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
    "ImmutableVersionConflictError",
    "InMemoryGrantStore",
    "LifecycleTransitionError",
    "ManifestValidationError",
    "PolicyDecision",
    "SQLiteStore",
    "SchemaVersionError",
    "StorageClosedError",
    "StorageError",
    "TaskAuthorizationContextUnavailable",
    "TaskAuthorizationDecision",
    "TaskAuthorizationError",
    "TaskAuthorizer",
    "TaskCallerContext",
    "TaskExecutionError",
    "TaskResult",
    "TaskResultStore",
    "TaskRunConflictError",
    "TaskRunner",
    "authorize",
    "transition_record",
]
