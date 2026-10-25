# Implementation Plan

## Delivery sequence

### Phase 0 — Contract and inventory (current pull request)

- [x] Inspect repository baseline.
- [x] Define distinct extension kinds and contract metadata.
- [x] Add versioned manifest schema and example.
- [x] Add manifest validator, unit tests, and pull-request CI.
- [x] Record architecture and threat model.
- [ ] Review/merge initial contract and treat schema changes as versioned API changes.

Exit gate: manifests can be reviewed and validated before an extension is approved or executed.

### Phase 1 — Registry model and read-only provider

- [ ] Define registry entity/state model and storage requirements.
- [ ] Add lifecycle state transitions with actor, version, source revision, permission request and review evidence.
- [ ] Implement one read-only repository metadata provider.
- [ ] Normalize results while preserving source IDs, timestamps, links and provenance.
- [ ] Add contract tests and operation-level audit events.
- [ ] Demonstrate disable/revoke behavior without external writes.

Exit gate: read-only operation is authorized, attributable, testable, and revocable.

### Phase 2 — Deterministic task runner

- [ ] Define execution envelope, typed inputs/outputs, timeout, resource budget and error taxonomy.
- [ ] Implement the manifest/configuration validation task as the first bounded action.
- [ ] Record extension/version/digest, actor, scope, input/output references, outcome and duration.
- [ ] Add queueing/retries only where tasks require asynchronous execution.
- [ ] Prove retries do not create duplicate side effects.

Exit gate: execution is bounded and its results can be traced and reproduced.

### Phase 3 — Event-driven integrations

- [ ] Verify webhook signatures and event/action types.
- [ ] Persist delivery IDs and implement idempotency.
- [ ] Add durable queue, backoff, dead-letter and operator-controlled replay.
- [ ] Scope installation tokens to repositories and permissions; prefer short-lived credentials.
- [ ] Test outages, duplicates, reordering, and partial failure.

Exit gate: delivery and recovery semantics are explicit and tested.

### Phase 4 — UI, provider packaging and AI tools

- [ ] Expose approved extensions and actual grants in a catalog UI/API.
- [ ] Add install/configure/validate/enable/disable/update/rollback state machine.
- [ ] Add provider packages behind narrow host-owned interfaces.
- [ ] Add MCP/tool interfaces only when a clear workflow requires them.
- [ ] Add UI contributions for inspection, configuration, comparison or navigation—not as a default requirement.
- [ ] Add per-operation authorization and approval for consequential writes.

Exit gate: users can inspect capabilities, data flows, source identity, run evidence, and revocation state.

### Phase 5 — Third-party runtime and ecosystem controls

- [ ] Add sandboxed execution, egress allowlists and resource quotas.
- [ ] Verify artifact digest, publisher/source provenance, license and dependency/SBOM evidence.
- [ ] Stage candidate updates, compare behavior and retain a rollback version.
- [ ] Add delegated publishers and contribution certification.
- [ ] Add quotas, retention policies, incident kill switch, backup/restore and health metrics.

Exit gate: each supported trust tier has an evidence-based approval and isolation policy.

## Non-goals for the first milestone

- No database/backend requirement yet.
- No public third-party marketplace.
- No arbitrary executable plugin installation.
- No general secret vault implemented by this repository.
- No production deployment or production mutation.
