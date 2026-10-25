# Loofy Extensions

A governed foundation for discovering, describing, validating, and eventually executing extensions across developer tools and connected services.

> **Current status:** manifest contract, reference validator, and an in-memory registry/policy/lifecycle core. This is not yet a production plugin runtime. Durable persistence, secret storage, queues, sandboxing, and third-party code execution remain out of scope.

## What this repository establishes

- A versioned JSON manifest contract for multiple extension kinds.
- Explicit capability declarations, requested permissions, network limits, secret references, and approval metadata.
- A schema validator and CI checks.
- An in-memory reference registry with immutable version identity, an explicit lifecycle state machine, and audit events.
- A default-deny capability authorization function requiring an exact, unexpired grant for a principal, capability, resource, and environment.
- Architecture, trust boundaries, threat model, contribution/security guidance, and an implementation roadmap.

## Important security boundary

A valid manifest does **not** grant permissions. Registering an extension does **not** execute its code. A policy decision from the reference module is demonstrative, not a substitute for authorization at the external operation boundary. The in-memory registry is not durable and is not suitable as a production source of truth.

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

See [extension type taxonomy](docs/architecture/extension-types.md) and [reference architecture](docs/architecture/reference-architecture.md).

## Validate locally

Python 3.12 or newer is recommended.

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover --start-directory tests --verbose
python scripts/validate_manifests.py
```

The GitHub Actions workflow runs the same checks for pull requests and pushes to main.

## Package core

The `loofy_extensions` package currently offers an in-memory reference implementation for the contract, registry, lifecycle and policy boundaries. It must not be treated as a durable registry or a plugin loader. See [reference implementation](docs/architecture/reference-implementation.md).

## Documentation

- Architecture: [reference architecture](docs/architecture/reference-architecture.md)
- Reference code boundaries: [reference implementation](docs/architecture/reference-implementation.md)
- Extension type taxonomy: [extension types](docs/architecture/extension-types.md)
- Architecture decision: [ADR 0001 — Extension Boundaries](docs/architecture/decisions/0001-extension-boundaries.md)
- Threat model: [security threat model](docs/security/threat-model.md)
- Implementation sequence: [roadmap](docs/roadmap/implementation-plan.md)
- [Contribution guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
