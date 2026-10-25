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

### Phase 2 — Durable registry and read-only provider (in progress)

- [ ] Define transactional persistence and migration requirements.
- [ ] Persist lifecycle state and audit events atomically.
- [x] Implement a narrow read-only GitHub.com repository metadata provider behind an injected transport contract.
- [x] Normalize repository identity, visibility, default branch, links, source timestamps, retrieval time and ETag provenance.
- [x] Add provider contract tests for identity mismatch, untrusted input, upstream failures and timestamp validity.
- [x] Add tenant scope to capability requests and grants; test cross-tenant denial.
- [x] Add a host-side metadata operation gateway that authorizes before outbound reads, fails closed on unavailable policy state, and emits decision/outcome events.
- [ ] Wire caller context and policy loaders to the actual host authentication, current grant store, and extension registry.
- [ ] Replace the in-memory audit sink with durable, access-controlled operation audit storage.
- [x] Add an in-memory grant issuance/revocation reference with injected tenant-membership and grant-scope checks, future-expiry validation, immutable IDs, and audit events.
- [x] Test grant issuance denial paths, issuer membership, high-impact approval presence, revocation, repeated revocation, and immutable grant identity.
- [ ] Wire membership and grant-scope callbacks to authoritative host identity and policy services.
- [ ] Replace process-local grant/revocation state and grant audit events with transactional durable storage.
- [x] Demonstrate issuance → authorized read → revoke → denied read and extension disable → denied read using a fake transport; no external GitHub operations are performed.

Exit gate: read-only operation is authorized, attributable, testable, and revocable. The provider and in-memory gateway are reference seams, not a production-ready authorization or audit service.

### Phase 3 — Deterministic task runner

- [ ] Define execution envelope, typed inputs/outputs, timeout, resource budget and error taxonomy.
- [ ] Implement the manifest/configuration validation task as the first bounded action.
- [ ] Record extension/version/digest, actor, scope, input/output references, outcome and duration.
- [ ] Add queueing/retries only where tasks require asynchronous execution.
- [ ] Prove retries do not create duplicate side effects.

Exit gate: execution is bounded and its results can be traced and reproduced.

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
