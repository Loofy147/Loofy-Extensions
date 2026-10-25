# Loofy Extensions

A governed foundation for discovering, describing, validating, and eventually executing extensions across developer tools and connected services.

> **Current status:** versioned manifests, in-memory registry and policy core, tenant-scoped grant lifecycle, read-only GitHub repository metadata adapter, host-side authorization/audit seam, and an allowlisted manifest-validation task runner. These are reference implementations, not a production plugin runtime. Durable persistence, production identity/approval verification, secret storage, isolated workers, and sandboxed third-party execution remain out of scope.

## What this repository establishes

- A versioned JSON manifest contract for multiple extension kinds.
- Explicit capability declarations, requested permissions, network limits, secret references, and approval metadata.
- A schema validator and CI checks.
- An in-memory reference registry with immutable version identity, explicit lifecycle transitions, and audit events.
- Default-deny capability authorization with exact tenant, principal, extension version, capability, resource, environment, and expiry matching.
- A read-only GitHub repository metadata provider behind a host-owned transport contract.
- A host-side gateway that authorizes and audits metadata reads before calling the provider.
- An in-memory grant authority with injectable tenant-membership and grant-scope checks, expiry validation, immutable grant IDs, revocation state, and grant lifecycle audit events.
- An allowlisted `manifest.validate` task runner with typed execution envelopes, input-size limits, content digests, attribution, idempotent run IDs, and no third-party code execution.
- Architecture, trust boundaries, threat model, contribution/security guidance, and an implementation roadmap.

## Important security boundary

A valid manifest does **not** grant permissions. Registering an extension does **not** execute its code. The reference policy does not establish identity. Grant issuance uses host-supplied verification callbacks; its grant store, registry and audit sinks are in-memory and are not suitable as production sources of truth.

## Extension types

| Kind | Best fit |
| --- | --- |
| GitHub App / hosted service | Persistent event-driven integration, synchronization, dashboards, external state |
| GitHub Action | Bounded task inside a CI workflow |
| Reusable workflow | Versioned multi-job orchestration and shared pipeline policy |
| Provider / adapter | A vendor-specific implementation behind a host-owned contract |
| MCP server / tool package | Typed operations available to assistant or workflow clients |
| UI extension | Navigation, inspection, configuration, or focused user interaction |
| Declarative extension | Metadata, rules, and configuration with no arbitrary code execution |
| Sandboxed artifact | Selected third-party executable workload behind isolation and review |

See [extension type taxonomy](docs/architecture/extension-types.md), [reference architecture](docs/architecture/reference-architecture.md), [Phase 1 contract review](docs/architecture/phase-1-contract-review.md), [read-only GitHub metadata provider](docs/architecture/github-metadata-provider.md), [authorized metadata gateway](docs/architecture/authorized-metadata-gateway.md), [grant issuance/revocation contract](docs/architecture/grant-issuance-and-revocation.md), and [deterministic task runner](docs/architecture/deterministic-task-runner.md).

## Validate locally

Python 3.12 or newer is recommended.

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover --start-directory tests --verbose
python scripts/validate_manifests.py
```

The GitHub Actions workflow runs the same checks for pull requests and pushes to main.

## Package core

The `loofy_extensions` package offers an in-memory reference implementation for manifests, registry, lifecycle, policy, grant issuance/revocation, a tenant-scoped metadata gateway, and the built-in `manifest.validate` task. The GitHub metadata provider is read-only and does not acquire credentials. The task runner loads no third-party code and is input-bounded, but it is not an isolated worker and has no durable result store. Identity, grant storage, and audit boundaries still require trusted host integration and durable production implementations.

## Documentation

- Architecture: [reference architecture](docs/architecture/reference-architecture.md)
- Phase 1 review: [lifecycle, authorization, and provenance contracts](docs/architecture/phase-1-contract-review.md)
- Read-only provider: [GitHub metadata provider](docs/architecture/github-metadata-provider.md)
- Authorization and audit boundary: [authorized metadata gateway](docs/architecture/authorized-metadata-gateway.md)
- Grant lifecycle: [grant issuance and revocation](docs/architecture/grant-issuance-and-revocation.md)
- Bounded host task: [deterministic manifest validation task runner](docs/architecture/deterministic-task-runner.md)
- Reference code boundaries: [reference implementation](docs/architecture/reference-implementation.md)
- Extension type taxonomy: [extension types](docs/architecture/extension-types.md)
- Architecture decision: [ADR 0001 — Extension Boundaries](docs/architecture/decisions/0001-extension-boundaries.md)
- Threat model: [security threat model](docs/security/threat-model.md)
- Implementation sequence: [roadmap](docs/roadmap/implementation-plan.md)
- [Contribution guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
