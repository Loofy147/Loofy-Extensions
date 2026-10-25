# Loofy Extensions

A governed foundation for discovering, describing, validating, and eventually executing extensions across developer tools and connected services.

> **Current status:** versioned manifests, reference validator, in-memory registry and policy core, read-only GitHub repository metadata adapter, and a tenant-scoped host-side authorization/audit seam. This is not yet a production plugin runtime. Durable persistence, secret storage, queues, and sandboxed third-party execution remain out of scope.

## What this repository establishes

- A versioned JSON manifest contract for multiple extension kinds.
- Explicit capability declarations, requested permissions, network limits, secret references, and approval metadata.
- A schema validator and CI checks.
- An in-memory reference registry with immutable version identity, explicit lifecycle transitions, and audit events.
- Default-deny capability authorization with exact tenant, principal, extension version, capability, resource, environment, and expiry matching.
- A read-only GitHub repository metadata provider behind a host-owned transport contract.
- A host-side gateway that authorizes and audits metadata reads before calling the provider.
- Architecture, trust boundaries, threat model, contribution/security guidance, and an implementation roadmap.

## Important security boundary

A valid manifest does **not** grant permissions. Registering an extension does **not** execute its code. The reference policy does not create grants or establish identity. The in-memory registry and audit sink are not durable and are not suitable as production sources of truth.

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

See [extension type taxonomy](docs/architecture/extension-types.md), [reference architecture](docs/architecture/reference-architecture.md), [Phase 1 contract review](docs/architecture/phase-1-contract-review.md), [read-only GitHub metadata provider](docs/architecture/github-metadata-provider.md), and [authorized metadata gateway](docs/architecture/authorized-metadata-gateway.md).

## Validate locally

Python 3.12 or newer is recommended.

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover --start-directory tests --verbose
python scripts/validate_manifests.py
```

The GitHub Actions workflow runs the same checks for pull requests and pushes to main.

## Package core

The `loofy_extensions` package offers an in-memory reference implementation for manifests, registry, lifecycle and policy boundaries. The GitHub metadata provider is read-only and does not acquire credentials. The gateway accepts trusted host context and policy loaders but is not a production identity provider or durable audit system.

## Documentation

- Architecture: [reference architecture](docs/architecture/reference-architecture.md)
- Phase 1 review: [lifecycle, authorization, and provenance contracts](docs/architecture/phase-1-contract-review.md)
- Read-only provider: [GitHub metadata provider](docs/architecture/github-metadata-provider.md)
- Authorization and audit boundary: [authorized metadata gateway](docs/architecture/authorized-metadata-gateway.md)
- Reference code boundaries: [reference implementation](docs/architecture/reference-implementation.md)
- Extension type taxonomy: [extension types](docs/architecture/extension-types.md)
- Architecture decision: [ADR 0001 — Extension Boundaries](docs/architecture/decisions/0001-extension-boundaries.md)
- Threat model: [security threat model](docs/security/threat-model.md)
- Implementation sequence: [roadmap](docs/roadmap/implementation-plan.md)
- [Contribution guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
