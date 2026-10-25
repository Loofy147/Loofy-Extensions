# Transactional SQLite Persistence Boundary

Status: local durable reference adapter. It persists extension state, grants, lifecycle/grant audit events, and host operation audit events. It is not a distributed store or a production identity service.

## Design boundary

SQLiteStore implements the registry facade's storage contract, the grant store operations consumed by GrantAuthority, and the operation audit sink consumed by AuthorizedGitHubMetadataReader. One database file can therefore hold extension versions, lifecycle audit events, capability grants, grant audit events, and correlated operation events.

No third-party runtime dependency is required; the adapter uses Python's standard-library sqlite3.

## Schema migration

The database creates a schema_migrations table and records the current schema version. Migrations are forward-only and applied under a write transaction. A database whose recorded version is newer than the code is rejected rather than silently rewritten.

Migration 1 creates:

- extension_records: immutable extension ID/version key, manifest digest, metadata, declared capability sets, lifecycle state, and UTC timestamps.
- lifecycle_audit_events: from/to state, actor, reason, approval reference, timestamp, and a foreign key to the extension version.
- capability_grants: exact tenant/principal/resource/environment scope, extension version, capability, grantor, expiry, approval reference, issuance time, and nullable revocation time.
- grant_audit_events: issued/revoked event detail with a foreign key to the grant.

Migration 2 creates:

- operation_audit_events: operation type, extension/version and manifest digest, principal, tenant, capability, resource, environment, outcome, decision/error code, timestamp, source ID when available, and a correlation ID.
- Indexes for tenant/resource/time queries and correlation-ID lookup.

The schema upgrade from v1 to v2 is tested; do not edit an applied migration in place. Future changes must add a new ordered migration and cover both upgrade fixtures and newer-schema rejection.

## Transaction guarantees

- Lifecycle transition: load current record, validate the transition, update state/timestamp, and insert its lifecycle event in one BEGIN IMMEDIATE transaction.
- Grant issuance: insert the immutable grant and issued event in one transaction. Identical retry is idempotent; reuse of a grant ID with different content is a conflict.
- Grant revocation: set revoked_at and insert the revoked event in one transaction. Repeated revocation is rejected.
- Operation audit: each event is appended in its own transaction. The gateway writes the authorization decision before making the outbound request; if that insert fails, the provider is not called. Completion/failure events use the same correlation ID.
- Audit failure: lifecycle/grant state changes roll back when their paired audit-row insertion fails. An operation-audit append failure aborts that append.
- Concurrency: SQLite's writer lock and busy timeout serialize database writers. This is not a distributed transaction service.

## Registry and gateway integration

~~~python
from loofy_extensions import ExtensionRegistry, SQLiteStore

with SQLiteStore("var/loofy-extensions.sqlite3") as store:
    registry = ExtensionRegistry(store=store)
    record = registry.register(manifest)
    # Pass store as the grant store and gateway audit sink as well.
~~~

The same live store instance can be passed as the grant store to GrantAuthority and as the audit sink to AuthorizedGitHubMetadataReader. The gateway generates a correlation ID per request and writes it onto authorization and outcome events.

## Important limitations

- Suitable as an embedded/local reference and single-host starting point; no multi-node coordination or high-availability guarantee is claimed.
- Caller identity, tenant membership, grantor authority, and approval verification must come from trusted host services.
- Operation events are persisted, but access controls, tamper-evidence, retention, backup/restore, encryption-at-rest policy and production monitoring still need to be defined.
- Grant and lifecycle event transaction guarantees apply within this database. Sending events to an external audit system requires an outbox or another explicit consistency design.
- This adapter does not store secrets, GitHub tokens, provider payloads, or task-runner results.

## Verification

The SQLite persistence tests cover schema v1→v2 migration, restart, lifecycle/grant/operation audit persistence, immutable version/grant conflicts, future-schema rejection, and transactional rollback under forced audit failures. Gateway tests verify correlated events and fail-closed behavior when a durable audit insert is rejected.

~~~sh
python -m unittest discover --start-directory tests --verbose
python scripts/validate_manifests.py
~~~
