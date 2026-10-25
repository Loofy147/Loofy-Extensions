"""Read-only provider adapters and host-side guarded readers."""

from .github_gateway import (
    AuthorizationContextUnavailable,
    AuthorizedGitHubMetadataReader,
    CallerContext,
    InMemoryOperationAuditSink,
    OperationAuditEvent,
    OperationAuthorizationError,
)
from .github_http import UrllibGitHubTransport
from .github_metadata import (
    GitHubHttpResponse,
    GitHubRepositoryMetadata,
    GitHubRepositoryMetadataProvider,
    ProviderError,
    ReadOnlyGitHubTransport,
    RepositoryLinks,
    RepositoryProvenance,
)

__all__ = [
    "AuthorizationContextUnavailable",
    "AuthorizedGitHubMetadataReader",
    "CallerContext",
    "GitHubHttpResponse",
    "GitHubRepositoryMetadata",
    "GitHubRepositoryMetadataProvider",
    "InMemoryOperationAuditSink",
    "OperationAuditEvent",
    "OperationAuthorizationError",
    "ProviderError",
    "ReadOnlyGitHubTransport",
    "RepositoryLinks",
    "RepositoryProvenance",
    "UrllibGitHubTransport",
]
