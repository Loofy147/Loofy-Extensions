# Threat Model and Security Baseline

## Assets to protect

- Repository/source code and artifacts.
- User, organization, tenant, and resource authorization boundaries.
- GitHub App installation tokens, webhook secrets, OAuth credentials, cloud identity, and vault references.
- Extension manifests, package revisions, provenance records, and policy grants.
- External side effects: pull requests, comments, merges, workflow dispatches, deployments, deletes, and notifications.
- Audit records and any retained source/event data.

## Trust boundaries

1. **Discovery → evaluation:** public metadata is untrusted; discovery never installs or executes.
2. **Manifest → policy:** requested capabilities are declarations, not grants.
3. **User interface/model → API:** UI visibility and tool descriptions are not authorization.
4. **Webhook → queue:** validate signature, event type, and delivery ID before processing.
5. **Extension → host:** third-party code must not inherit host credentials, filesystem, network, or ambient identity.
6. **Runner → external system:** every operation must be authorized for the actual principal, repository, environment, and version.
7. **Logs/artifacts → readers:** redact credentials and restrict access/retention.

## Threats and controls

| Threat | Minimum control |
| --- | --- |
| Overbroad permission request | Named capabilities, default deny, review of each scope and resource |
| Compromised extension update | Immutable revision/digest, provenance check, staged update, rollback pointer |
| Malicious dependency or Action | Verified source, pinned full commit SHA/digest, dependency/lockfile review |
| Webhook spoofing/replay | HMAC signature verification, constant-time compare, delivery dedupe |
| Secret disclosure | Vault-backed reference only, short-lived credentials, redaction, least privilege |
| Cross-tenant access | Tenant-bound grants and tokens; authorization at every operation |
| Untrusted PR or issue content | Treat as data; never interpolate directly into shell commands or policy |
| Unsafe auto-remediation | Separate analysis and write capabilities; preview, approval and recovery |
| Resource exhaustion or tool loops | Wall-clock, CPU, memory, retry, request, and spend limits |
| Silent destructive action | Explicit authorization, auditable intent/result, recovery or compensation path |
| Stale/incorrect external data | Provenance, source timestamps, conflict state, no silent overwrites |
| Extension removal leaves access behind | Revoke tokens/subscriptions, cancel schedules/jobs, record retained/deleted data |

## Trust tiers

- **T0 — Declarative:** metadata/configuration only; no execution or secrets.
- **T1 — First-party deterministic:** reviewed and tested internal task with scoped capability grants.
- **T2 — Verified hosted connector:** publisher/source/privacy/licensing/permission review; contract tests.
- **T3 — Third-party executable:** isolated worker, deny-by-default egress, quotas, immutable artifact identity and explicit enablement.
- **T4 — Consequential writer:** merge, deploy, delete, secret rotation, public or financial action; scoped step-up approval and recovery plan.

Assign the effective tier from the highest-risk behavior or requested operation, not marketing claims. A single extension can require different gates for read-only and write operations.

## Baseline before enabling execution

- [ ] Authorization is enforced server-side for every operation.
- [ ] Grants are scoped to principal, tenant, resource, environment and capability.
- [ ] Credentials are never stored in manifests or ordinary configuration.
- [ ] Webhook signature, replay, deduplication and idempotency behavior is tested.
- [ ] Third-party runtime is isolated with bounded CPU, memory, wall-clock, disk and egress.
- [ ] Artifacts are pinned by immutable identity and source provenance is recorded.
- [ ] Logs and execution evidence are redacted and access-controlled.
- [ ] Disable/uninstall revokes credentials and cancels triggers and queued work.
- [ ] High-impact writes have preview, approval, audit and rollback/compensation.
- [ ] Backup/restore and incident kill switch are tested.
