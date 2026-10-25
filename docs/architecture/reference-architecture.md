# Reference Architecture

## Scope and status

This document describes the target architecture and distinguishes implemented reference code from future services. The repository currently contains a declarative manifest contract, schema validator, and an in-memory reference registry/policy/lifecycle module. It does not yet implement the production services below.

## Design rules

1. Keep the core small and make extension points explicit.
2. Treat an extension as a principal with requested capabilities, not as trusted code.
3. Separate declaration, review, grant, installation, activation, execution, and removal.
4. Keep credentials out of manifests and logs; store only scoped vault references in configuration.
5. Separate read/analysis from mutation. Add stronger approval gates as impact rises.
6. Prefer a modular monolith while preserving service boundaries in interfaces.
7. Make executions attributable, bounded, observable, retryable where appropriate, and safe to disable.

## Logical architecture

```text
UI / CLI / API / assistant tools
            |
Identity + policy gateway + approval checks
            |
Extension registry + schema validator + lifecycle manager
            |
    +-------+------------+-----------------+
    |                    |                 |
Provider adapters   Action/job runner   UI extension points
    |                    |                 |
    +-------- event and execution contracts+
                         |
Durable queue / scheduler / retry / dead-letter handling
                         |
External systems: GitHub, CI, storage, issue trackers, APIs, MCP servers

Shared services: secret vault, typed configuration, provenance store,
audit log, metrics/traces, rate limits, health checks, backup and recovery.
```

## Component ownership

| Component | Owns | Must not do |
| --- | --- | --- |
| Registry | Stable ID, publisher, version, source, digest, license, review state, compatibility | Execute code simply because metadata was discovered |
| Schema validator | Contract shape and required metadata | Treat a valid manifest as permission to act |
| Lifecycle manager | Install/configure/validate/enable/update/disable/uninstall state | Perform privileged writes without policy and audit |
| Policy gateway | Principal, tenant, resource and action-level authorization | Trust a UI, extension description, or model output as authority |
| Secret service | Encrypted values, rotation, short-lived credential issuance | Expose raw secrets to the registry, event payload, UI, or model context |
| Connector adapter | Vendor-specific API, event normalization and rate-limit handling | Bypass policy for privileged actions |
| Job runner | Bounded task execution with resource constraints | Run third-party code with host credentials or unrestricted network/filesystem access |
| Event queue | Delivery deduplication, retries, replay and dead-letter records | Assume events arrive once or in order |
| Provenance layer | Source identities, timestamps, IDs, artifacts, links, conflict records | Erase origin data or silently overwrite conflicts |
| Audit/observability | Version, scope, actor, input/output references, duration, status and policy result | Log secrets or retain unnecessary sensitive payloads |

## Implemented reference slice

The `loofy_extensions` package demonstrates several boundaries in-process:

- A schema-backed registry stores a validated manifest projection under a stable `(extension_id, version)` key.
- The manifest is canonicalized and hashed; an identical registration is idempotent, while different content for an existing key is rejected.
- A lifecycle transition map blocks invalid jumps and emits immutable audit-event objects.
- A capability policy denies by default and requires an exact grant matching extension version, principal, capability, resource, and environment. Grants must be unexpired, and high-impact permissions require approval evidence.
- No registered code is loaded or executed.

These are reference semantics only. There is no persistent storage, transactional cross-process concurrency, tenant store, external API enforcement, credential minting, durable audit ledger, sandbox, or queue yet. The reference grant model must not be used as the sole authorization control for production side effects.

## Extension lifecycle

Use explicit states: Discovered → Evaluating → Approved → Installed → Configured → Validated → Enabled. Degraded or Suspended may be reached from active states. Updating validates a candidate before promotion. Disabled and Uninstalled stop execution and revoke access; retention and deletion follow policy.

Transitions that broaden access, enable writes, or affect production require recorded approval bound to the exact extension version/digest and resource scope.

## Event semantics

Assume at-least-once delivery unless a provider's contract establishes otherwise. Verify webhook signatures, validate event/action types, acknowledge quickly, enqueue durably, and de-duplicate delivery IDs. Handlers with side effects need idempotency keys and bounded retry/backoff. Record partial failures and compensation steps rather than claiming cross-system atomicity.

## First production implementation slices

1. Replace the process-local registry with a transactional persistence adapter behind the same interface.
2. Add a read-only repository metadata provider, proving identity, scopes, normalized output, and provenance.
3. Define an execution envelope, then add a deterministic validation task before any third-party code runner.
4. Add per-operation authorization, secret issuance, audit durability, and explicit revocation.
5. Add webhook intake, queues, idempotency, retry/backoff, and dead-letter handling only when event-driven integrations require them.

Do not start with arbitrary third-party code execution, public plugin submissions, production deployment, or broad PAT collection.

## External references

- GitHub Apps and permissions: https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app
- GitHub Actions secure use: https://docs.github.com/en/actions/reference/security/secure-use
- GitHub webhook validation: https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
- Backstage backend extension points: https://backstage.io/docs/backend-system/architecture/index/
- OpenFeature provider contract: https://openfeature.dev/specification/sections/providers/
- JSON Schema Draft 2020-12: https://json-schema.org/draft/2020-12
