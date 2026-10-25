# Implementation Plan

## Delivery sequence

### Phase 0 — Contract and inventory (completed)

- [x] Inspect repository baseline.
- [x] Define distinct extension kinds and contract metadata.
- [x] Add versioned manifest schema and example.
- [x] Add manifest validator, unit tests, and pull-request CI.
- [x] Record architecture and threat model.
- [x] Merge the initial contract baseline; schema changes are treated as versioned API changes.

Exit gate: manifests can be reviewed and validated before an extension is approved or executed.

### Phase 1 — In-memory reference core (contract baseline hardened)

- [x] Add validated registration, immutable extension-version identity and manifest digest.
- [x] Define a lifecycle state machine with actor, reason, approval evidence and audit events.
- [x] Add default-deny capability authorization with exact scope and expiry checks.
- [x] Add behavioral tests for rejection paths and policy scope.
- [x] Review lifecycle recovery, capability-risk classification, grant expiry and timestamp semantics.
- [x] Document approval-reference limitations and the distinction between manifest, artifact and source provenance.
- [x] Run the full unit suite and manifest validator successfully in CI.

Exit gate: the reference contract is testable without external credentials or writes. This is not a production authorization or persistence system.

### Phase 2 — Registry, read-only provider and grant lifecycle (in progress)

- [x] Define transactional persistence and ordered schema migrations.
- [x] Persist extension lifecycle state and lifecycle audit events atomically in the SQLite reference adapter.
- [x] Restrict existing/new SQLite main database files and active WAL/SHM sidecars to owner-only permissions on POSIX hosts.
- [x] Implement a narrow read-only GitHub.com repository metadata provider behind an injected transport contract.
- [x] Normalize repository identity, visibility, default branch, links, source timestamps, retrieval time and ETag provenance.
- [x] Add provider contract tests for identity mismatch, untrusted input, upstream failures and timestamp validity.
- [x] Add tenant scope to capability requests and grants; test cross-tenant denial.
- [x] Add a host-side metadata operation gateway that authorizes before outbound reads and fails closed if the pre-call audit append fails.
- [x] Persist operation audit events in SQLite and add correlation IDs across authorization and outcome events.
- [ ] Wire caller context and policy loaders to the actual host authentication, current grant store, and extension registry.
- [ ] Add production audit access controls, tamper-evidence/retention policy, and operational monitoring.
- [x] Add a grant issuance/revocation reference with host-supplied tenant-membership and grant-scope checks, future-expiry validation, immutable IDs, and audit events.
- [x] Persist grant state and corresponding grant audit events atomically.
- [x] Test grant issuance denial paths, issuer membership, high-impact approval presence, revocation, repeated revocation, and immutable grant identity.
- [ ] Wire membership, approval verification and grant-scope callbacks to authoritative host identity and policy services.
- [x] Demonstrate issuance → authorized read → revoke → denied read and extension disable → denied read using a fake transport; no external GitHub operations are performed.
- [x] Test process-style restart, schema v1→v3 migrations, future-schema rejection, and rollback when lifecycle, grant, or operation-audit insertion fails.

Exit gate: the local reference adapter persists state atomically and the metadata gateway can record auditable, correlated decisions. Production use still requires authoritative caller identity, membership/approval verification, protected audit access, and production operational controls.

### Phase 3 — Deterministic task runner (in progress)

- [x] Define a typed execution envelope, stable error codes, JSON-only input contract and host-owned task allowlist.
- [x] Implement `manifest.validate` as the first bounded host task; no third-party code or user-selected entrypoint is executed.
- [x] Record run ID, target extension/version, actor, tenant, scope, input/output digests, outcome and duration.
- [x] Enforce a maximum input size and reject unsupported task IDs and non-JSON inputs.
- [x] Make identical retries with the same run ID idempotent and reject changed requests that reuse a run ID.
- [x] Add optional SQLite-backed task results and request fingerprints; validate replay and run-ID conflicts across a process-style restart.
- [x] Add a host-side task authorization wrapper that overrides envelope identity from trusted caller context, checks policy before execution, and audits correlated outcomes.
- [ ] Bind the authorization callback to the host's authoritative identity and task/resource policy service.
- [x] Add opt-in isolated subprocess execution for the built-in manifest validator, with a wall-clock deadline, POSIX CPU/address-space/core-file limits, and bounded JSON request/response messages.
- [ ] Design full process/network sandboxing before adding any third-party or otherwise untrusted task; the validator worker is not a general plugin sandbox.
- [ ] Add queues only when a task requires asynchronous execution.

Exit gate: the allowlisted validation task is deterministic, input-bounded, optionally durable, and can be wrapped in a fail-closed authorization/audit boundary. The callback itself must come from trusted host services.

### Phase 4 — Event-driven integrations

- [ ] Verify webhook signatures and event/action types.
- [ ] Persist delivery IDs and implement idempotency.
- [ ] Add durable queue, backoff, dead-letter and operator-controlled replay.
- [ ] Scope installation tokens to repositories and permissions; prefer short-lived credentials.
- [ ] Test outages, duplicates, reordering, and partial failure.

Exit gate: delivery and recovery semantics are explicit and tested.

### Phase 5 — UI, provider packaging and AI tools

- [ ] Expose approved extensions and actual grants in a catalog UI/API.
- [ ] Add install/configure/validate/enable/disable/update/rollback state machine.
- [ ] Add provider packages behind narrow host-owned interfaces.
- [ ] Add MCP/tool interfaces only when a clear workflow requires them.
- [ ] Add UI contributions for inspection, configuration, comparison or navigation—not as a default requirement.
- [ ] Add per-operation authorization and approval for consequential writes.

Exit gate: users can inspect capabilities, data flows, source identity, run evidence, and revocation state.

### Phase 6 — Third-party runtime and ecosystem controls

- [ ] Add sandboxed execution, egress allowlists and resource quotas.
- [ ] Verify artifact digest, publisher/source provenance, license and dependency/SBOM evidence.
- [ ] Stage candidate updates, compare behavior and retain a rollback version.
- [ ] Add delegated publishers and contribution certification.
- [ ] Add quotas, retention policies, incident kill switch, backup/restore and health metrics.

Exit gate: each supported trust tier has an evidence-based approval and isolation policy.

## Non-goals for the current milestone

- No general-purpose production backend before its need is demonstrated by the next milestone.
- No public third-party marketplace.
- No arbitrary executable plugin installation.
- No general secret vault implemented by this repository.
- No production deployment or production mutation.
