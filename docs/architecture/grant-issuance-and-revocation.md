# Grant Issuance and Revocation Reference

Status: in-memory reference implementation. This establishes testable boundaries; it is not a production grant service or durable authorization source of truth.

## Purpose

The grant authority separates grant creation and revocation from the decision function that consumes grants. It is deliberately callback-driven: identity, tenant membership, current extension state and grantor authority must come from the host, not from extension manifests or user-controlled request fields.

## Issuance contract

A request is rejected unless:
- all actor, principal, tenant, capability, resource, environment and reason fields are present;
- the expiry timestamp is timezone-aware and strictly in the future;
- the exact extension ID/version is present in the trusted record loader and is enabled;
- the requested capability appears in that version's requested permissions;
- both the target principal and grant issuer are verified members of the tenant;
- the issuer is authorized for the requested tenant, capability, resource and environment scope;
- a high-impact capability carries an approval reference.

The approval reference is only checked for presence. This code does not verify the approval, issuer identity or cryptographic binding. A production approval service must bind evidence to the exact action, principal, tenant, extension digest/version, capability, resource, environment, decision and expiry.

## Revocation contract

The in-memory store holds immutable grant content under a stable grant ID and tracks revocation separately. A grant ID cannot be reused for different content. Identical store-level retries are idempotent; revoking an already-revoked or missing grant is rejected. Revoked grants are excluded from `active_grants()`, so a caller that obtains grants from that source will deny the revoked grant on the next policy evaluation.

The revocation operation checks tenant membership and scope authority before changing store state. The store operation itself updates revocation state and appends its audit event under one process-local lock.

## Audit events and guarantees

Issuance and revocation append events including actor, subject principal, tenant, extension version, capability, resource, environment, reason and UTC timestamp. This store keeps both grant state and audit records only in process memory. Restart loses both; the lock is not a distributed transaction.

## Production requirements not implemented here

- Authenticate callers and derive caller context from the host identity layer.
- Back the callbacks with authoritative, current tenant membership and grantor authorization data.
- Use transactional persistence to write grant/revocation state and audit events atomically.
- Define transaction isolation and race handling between grant use, revocation and operation execution.
- Add tenant-bound persistence, grant query indexing, retention and access controls.
- Verify approval evidence and associate it to immutable extension/artifact identity.
- Re-check authorization at the external operation boundary immediately before side effects.
- Test the disable/revoke path against live grant loaders without performing external writes.

The reference implementation must not be treated as a security boundary until these host responsibilities are met.
