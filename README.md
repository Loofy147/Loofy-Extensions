# Loofy Extensions

A governed foundation for discovering, describing, validating, and eventually executing extensions across developer tools and connected services.

> **Current status:** versioned manifests, an in-memory registry/policy core, an optional transactional SQLite registry/grant adapter, tenant-scoped grant lifecycle, a read-only GitHub repository metadata provider, a host-side authorization/audit seam, and an allowlisted manifest-validation task runner. These are reference implementations, not a production plugin runtime. Production identity/approval verification, durable production audit operations, secret storage, isolated workers, and sandboxed third-party execution remain out of scope.

## What this repository establishes

- A versioned JSON manifest contract for multiple extension kinds.
- Explicit capability declarations, requested permissions, network limits, secret references, and approval metadata.
- A schema validator and CI checks.
- A registry facade with immutable extension-version identity and lifecycle transitions; it can use the original in-memory mode or the SQLite persistence adapter.
- Default-deny capability authorization with exact tenant, principal, extension version, capability, resource, environment, and expiry matching.
- A read-only GitHub repository metadata provider behind a host-owned transport contract.
- A host-side gateway that authorizes and audits metadata reads before calling the provider.
- A grant authority with injectable tenant-membership and grant-scope checks, expiry validation, immutable grant IDs, revocation state, and grant lifecycle audit events.
- A transactional SQLite reference store for extension records, lifecycle audit events, grants, and grant audit events. State changes and their corresponding audit rows are committed atomically.
- An allowlisted `manifest.validate` task runner with typed execution envelopes, input-size limits, content digests, attribution, idempotent run IDs, and no third-party code execution.
- Architecture, trust boundaries, threat model, contribution/security guidance, migration requirements, and an implementation roadmap.

## Important security boundary

A valid manifest does **not** grant permissions. Registering an extension does **not** execute its code. The reference policy does not establish identity. Grant issuance still relies on host-supplied verification callbacks. SQLite persistence improves durability and atomicity on one host; it does not create a production identity system, distributed database, cryptographically tamper-evident audit system, or production authorization boundary.

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

See [extension type taxonomy](docs/architecture/extension-types.md), [reference architecture](docs/architecture/reference-architecture.md), [Phase 1 contract review](docs/architecture/phase-1-contract-review.md), [read-only GitHub metadata provider](docs/architecture/github-metadata-provider.md), [authorized metadata gateway](docs/architecture/authorized-metadata-gateway.md), [grant issuance/revocation contract](docs/architecture/grant-issuance-and-revocation.md), [deterministic task runner](docs/architecture/deterministic-task-runner.md), and [SQLite persistence boundary](docs/architecture/sqlite-persistence.md).

## Validate locally

Python 3.12 or newer is recommended.

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover --start-directory tests --verbose
python scripts/validate_manifests.py
```

The GitHub Actions workflow runs the same checks for pull requests and pushes to main.

## Use SQLite persistence locally

```python
from loofy_extensions import ExtensionRegistry, SQLiteStore

with SQLiteStore("var/loofy-extensions.sqlite3") as store:
    registry = ExtensionRegistry(store=store)
    record = registry.register(manifest)
```

The SQLite adapter persists extension state and lifecycle audit events, and also implements the grant-store contract used by `GrantAuthority`. Use one store/database for the records and grants that must share foreign keys and transactions. See the [persistence contract](docs/architecture/sqlite-persistence.md) for migrations, restart behavior, transaction guarantees, and production limitations.

## Package core

The package offers both the original in-memory reference registry and an optional local SQLite store. The GitHub metadata provider is read-only and does not acquire credentials. The gateway and grant authority require trusted host callbacks; their identity and authorization dependencies are not created by SQLite. The built-in task runner loads no third-party code and is input-bounded, but it is not an isolated worker and its run history is not yet durable.

## Documentation

- Architecture: [reference architecture](docs/architecture/reference-architecture.md)
- Phase 1 review: [lifecycle, authorization, and provenance contracts](docs/architecture/phase-1-contract-review.md)
- Read-only provider: [GitHub metadata provider](docs/architecture/github-metadata-provider.md)
- Authorization and audit boundary: [authorized metadata gateway](docs/architecture/authorized-metadata-gateway.md)
- Grant lifecycle: [grant issuance and revocation](docs/architecture/grant-issuance-and-revocation.md)
- Persistence: [transactional SQLite adapter](docs/architecture/sqlite-persistence.md)
- Bounded host task: [deterministic manifest validation task runner](docs/architecture/deterministic-task-runner.md)
- Reference code boundaries: [reference implementation](docs/architecture/reference-implementation.md)
- Extension type taxonomy: [extension types](docs/architecture/extension-types.md)
- Architecture decision: [ADR 0001 — Extension Boundaries](docs/architecture/decisions/0001-extension-boundaries.md)
- Threat model: [security threat model](docs/security/threat-model.md)
- Implementation sequence: [roadmap](docs/roadmap/implementation-plan.md)
- [Contribution guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
