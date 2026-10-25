# Loofy Extensions

A governed foundation for discovering, describing, validating, and eventually executing extensions across developer tools and connected services.

> **Current status:** versioned manifests, an optional transactional SQLite registry/grant store, tenant-scoped grant lifecycle, a read-only GitHub repository metadata provider, host-side authorization gateways, durable operation-audit storage, an allowlisted manifest-validation task runner with optional isolated worker execution, and durable task results. These are reference implementations, not a production plugin runtime. Production identity/approval verification, hardened audit access controls, secret storage, and sandboxed third-party execution remain out of scope.

## What this repository establishes

- A versioned JSON manifest contract for multiple extension kinds.
- Explicit capability declarations, requested permissions, network limits, secret references, and approval metadata.
- A schema validator and CI checks.
- A registry facade with immutable extension-version identity and lifecycle transitions; it can use the original in-memory mode or the SQLite persistence adapter.
- Default-deny capability authorization with exact tenant, principal, extension version, capability, resource, environment, and expiry matching.
- A read-only GitHub repository metadata provider behind a host-owned transport contract.
- A host-side gateway that authorizes and audits metadata reads before calling the provider.
- A grant authority with injectable tenant-membership and grant-scope checks, expiry validation, immutable grant IDs, revocation state, and grant lifecycle audit events.
- A transactional SQLite store for extension records, lifecycle events, grants, grant events, operation-level gateway audit records, and optional task-run results.
- Owner-only SQLite database/WAL/SHM permissions on POSIX hosts.
- Correlation IDs that link metadata/task authorization and outcome events.
- An allowlisted `manifest.validate` task runner with typed execution envelopes, input-size limits, content digests, attribution, run-ID idempotency, and no third-party code execution.
- Optional isolated subprocess validation with a wall-clock deadline, POSIX CPU/address-space/core-file limits, and bounded JSON request/response messages.
- An optional task authorization wrapper that derives attribution from trusted host caller context and fails closed when policy lookup or the pre-run audit append fails.
- A canonical host-owned task-runner manifest at `examples/extensions/task-runner/extension.json`, declaring `task.manifest.validate` and a deny-by-default network policy.
- A capability-policy adapter that maps the allowlisted `manifest.validate` task to `task.manifest.validate` and evaluates it using the existing tenant-scoped grant policy.
- Optional SQLite-backed task results with persisted request fingerprints, so identical run IDs remain idempotent across restarts and conflicting reuse is rejected.

## Important security boundary

A valid manifest does **not** grant permissions. Registering an extension does **not** execute its code. The reference policy does not establish identity. Grant issuance and task authorization rely on host-supplied verification callbacks. SQLite persistence provides local durability and transaction atomicity; it does not create an identity system, distributed database, cryptographically tamper-evident audit, or complete production access controls.

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

See [extension type taxonomy](docs/architecture/extension-types.md), [reference architecture](docs/architecture/reference-architecture.md), [Phase 1 contract review](docs/architecture/phase-1-contract-review.md), [read-only GitHub metadata provider](docs/architecture/github-metadata-provider.md), [authorized metadata gateway](docs/architecture/authorized-metadata-gateway.md), [grant issuance/revocation contract](docs/architecture/grant-issuance-and-revocation.md), [deterministic task runner](docs/architecture/deterministic-task-runner.md), [authorized task runner](docs/architecture/authorized-task-runner.md), and [SQLite persistence boundary](docs/architecture/sqlite-persistence.md).

## Validate locally

Python 3.12 or newer is recommended.

~~~sh
python -m pip install -r requirements-dev.txt
python -m unittest discover --start-directory tests --verbose
python scripts/validate_manifests.py
~~~

The GitHub Actions workflow runs the same checks for pull requests and pushes to main.

## Use SQLite persistence locally

~~~python
from loofy_extensions import ExtensionRegistry, SQLiteStore, TaskRunner

with SQLiteStore("var/loofy-extensions.sqlite3") as store:
    registry = ExtensionRegistry(store=store)
    record = registry.register(manifest)

    runner = TaskRunner(store=store)
    result = runner.run(envelope)
~~~

The same store can be passed as the grant store to `GrantAuthority` and as the operation audit sink to `AuthorizedGitHubMetadataReader` or `AuthorizedTaskRunner`. See [SQLite persistence](docs/architecture/sqlite-persistence.md) for migration and transaction guarantees.

## Package core

The package offers both the original in-memory reference registry and an optional local SQLite store. The GitHub metadata provider is read-only and does not acquire credentials. The gateway and grant/task authorization wrappers require trusted host callbacks; persistence does not authenticate a caller or verify approval evidence. On POSIX hosts, SQLite database and active sidecar files are restricted to owner-only permissions; this is not encryption at rest or a substitute for backup and directory access policy. The built-in task runner loads no third-party code and is input-bounded. Opt-in isolated validation runs the built-in schema check in a separate process with a wall-clock deadline and POSIX CPU/address-space limits; this is not a network sandbox or general-purpose plugin sandbox. Applications exposed to users should use `AuthorizedTaskRunner` or an equivalent operation boundary rather than exposing the bare task runner.

## Documentation

- Architecture: [reference architecture](docs/architecture/reference-architecture.md)
- Phase 1 review: [lifecycle, authorization, and provenance contracts](docs/architecture/phase-1-contract-review.md)
- Read-only provider: [GitHub metadata provider](docs/architecture/github-metadata-provider.md)
- Authorization and audit boundary: [authorized metadata gateway](docs/architecture/authorized-metadata-gateway.md)
- Grant lifecycle: [grant issuance and revocation](docs/architecture/grant-issuance-and-revocation.md)
- Persistence: [transactional SQLite adapter](docs/architecture/sqlite-persistence.md)
- Bounded host task: [deterministic manifest validation task runner](docs/architecture/deterministic-task-runner.md)
- Task authorization: [authorized task runner boundary](docs/architecture/authorized-task-runner.md)
- Reference code boundaries: [reference implementation](docs/architecture/reference-implementation.md)
- Extension type taxonomy: [extension types](docs/architecture/extension-types.md)
- Architecture decision: [ADR 0001 — Extension Boundaries](docs/architecture/decisions/0001-extension-boundaries.md)
- Threat model: [security threat model](docs/security/threat-model.md)
- Implementation sequence: [roadmap](docs/roadmap/implementation-plan.md)
- [Contribution guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
