"""Read-only provider adapters."""

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
    "GitHubHttpResponse",
    "GitHubRepositoryMetadata",
    "GitHubRepositoryMetadataProvider",
    "ProviderError",
    "ReadOnlyGitHubTransport",
    "RepositoryLinks",
    "RepositoryProvenance",
]
