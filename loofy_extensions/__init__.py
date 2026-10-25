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

__all__ = [
    "AuditEvent",
    "CapabilityGrant",
    "CapabilityRequest",
    "DuplicateExtensionVersionError",
    "ExtensionKey",
    "ExtensionRecord",
    "ExtensionRegistry",
    "ExtensionState",
    "GrantAuditEvent",
    "GrantAuthority",
    "GrantConflictError",
    "GrantPolicyError",
    "InMemoryGrantStore",
    "LifecycleTransitionError",
    "ManifestValidationError",
    "PolicyDecision",
    "authorize",
    "transition_record",
]
