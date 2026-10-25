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

__all__ = [
    "AuditEvent",
    "CapabilityGrant",
    "CapabilityRequest",
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
    "TaskExecutionError",
    "TaskResult",
    "TaskResultStore",
    "TaskRunConflictError",
    "TaskRunner",
    "authorize",
    "transition_record",
]
