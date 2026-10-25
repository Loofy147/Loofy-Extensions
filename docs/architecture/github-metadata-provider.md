# Read-only GitHub Repository Metadata Provider

Status: first provider contract; implemented with an injected transport and tested against deterministic fixtures. It is not yet wired to live credentials or an application runtime.

## Purpose

The provider reads repository metadata from the GitHub.com repository endpoint and returns a normalized, immutable value object. It preserves GitHub's stable repository ID, canonical names and links, source creation/update timestamps, retrieval time, ETag (when provided), and explicit provider/operation provenance.

## Contract

- Operation identifier: `repository.metadata.read`.
- Endpoint: `GET https://api.github.com/repos/{owner}/{repo}`.
- No create/update/delete methods are exposed.
- HTTP transport, token acquisition, timeout, TLS configuration and rate-limit handling are injected by the host. The provider itself does not accept or store credentials.
- Current adapter deliberately accepts only the canonical GitHub.com API origin; GitHub Enterprise support must be introduced through an explicit host allowlist, not by accepting arbitrary HTTPS URLs.
- Owner and repository names are validated as single path segments before the transport is called.
- Non-2xx responses, invalid source identity, untrusted links, malformed fields and naive timestamps produce stable, non-secret-bearing provider errors.
- Provenance distinguishes the source resource ID and source update time from the time this adapter retrieved the record.

## Output shape

`GitHubRepositoryMetadata` contains normalized repository fields, `RepositoryLinks`, and `RepositoryProvenance`. Timestamp fields are timezone-aware UTC datetimes. The adapter does not silently discard source identity or source freshness metadata.

## Security boundaries

A host adapter must:
1. provide a transport that sends only HTTP GET requests to an approved host;
2. keep tokens in the host's secret subsystem and scope tokens to the smallest required repository permissions;
3. configure connect/read timeouts, TLS verification, rate-limit handling and bounded retry behavior;
4. authorize access to the requested repository before returning private metadata;
5. record the actual principal, tenant, requested repository, response outcome and correlation ID in the operation audit at the integration boundary;
6. avoid logging Authorization headers, token material or raw upstream error bodies.

A successful provider response is data, not authorization to perform a later write. Any future write provider must use a separate capability and an operation-boundary authorization check.

## Tests and current limitations

Run all project tests with:

```sh
python -m unittest discover --start-directory tests --verbose
python scripts/validate_manifests.py
```

Fixture tests cover identity and provenance normalization, ETag preservation, invalid path segments, upstream failure, malformed timestamps, invalid local clocks, and repository identity mismatch.

Not implemented: live HTTP transport, authentication, pagination, durable registry, cache, webhooks, GitHub writes, or production deployment. The narrow contract makes those separable follow-on tasks.
