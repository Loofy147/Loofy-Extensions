# Transactional SQLite Persistence Boundary

Status: local durable reference adapter. It proves state and audit records can be persisted atomically through one database transaction. It is not a distributed store or a production identity service.

## Design boundary

`SQLiteStore` implements the existing registry facade's storage contract and the grant store operations consumed by `GrantAuthority`. The same database file stores extension versions, lifecycle audit events, capability grants, and grant audit events. The manifest validator and lifecycle policy remain outside SQL; the storage layer persists validated immutable records and executes lifecycle transitions under a write transaction.

No new third-party runtime dependency is required: the adapter uses Python's standard-library `sqlite3` module.

## Schema migration

The database creates a `schema_migrations` table and records the current schema version. Migration 1 creates:

- `extension_records`: immutable extension ID/version key, manifest digest, metadata, declared capability sets, lifecycle state, and UTC timestamps.
- `lifecycle_audit_events`: from/to state, actor, reason, approval reference, timestamp, and a foreign key to its extension version.
- `capability_grants`: exact tenant/principal/resource/environment scope, extension version, capability, grantor, expiry, approval reference, issuance time, and nullable revocation time.
- `grant_audit_events`: issued/revoked event detail with a foreign key to the grant.

Scope and lifecycle indexes support the initial query patterns. Foreign keys are enabled and checked by the adapter. A database whose recorded schema version is newer than the code is rejected rather than silently rewritten.

Future schema changes must add a new ordered migration, update `CURRENT_SCHEMA_VERSION`, and test both upgrade behavior and the previous schema fixture. Do not edit an already-applied migration in place.

## Transaction guarantees

- Lifecycle transition: load current record, validate the requested transition, update state/timestamp, and insert its audit event inside one `BEGIN IMMEDIATE` transaction.
- Grant issuance: insert the immutable grant and the `issued` event in one transaction. An identical retry is idempotent; reusing a grant ID for different content is a conflict.
- Grant revocation: set `revoked_at` and insert the `revoked` event in one transaction. Repeated revocation is rejected.
- Audit failure: if the paired event cannot be inserted, the state mutation rolls back with it.
- Concurrency: SQLite's writer lock and busy timeout serialize database writers. This is not a replacement for a distributed transaction service.

## Registry integration

The existing `ExtensionRegistry` remains in-memory by default. To use durable storage:

```python
from loofy_extensions import ExtensionRegistry, SQLiteStore

store = SQLiteStore("var/loofy-extensions.sqlite3")
registry = ExtensionRegistry(store=store)

# Validate and register an extension manifest through the normal registry API.
record = registry.register(manifest)
```

Use the same live `SQLiteStore` instance for `GrantAuthority` and the metadata gateway's grant/record loaders. Close it during orderly shutdown. Reopening a new `SQLiteStore` with the same path restores extension records, lifecycle events, grants, revocation state, and grant audit events.

## Important limitations

- Suitable as an embedded/local reference and single-host starting point; no multi-node coordination or high-availability guarantee is claimed.
- Grant issuance still needs trusted host callbacks for identity, tenant membership, and scope authority. Approval references are not cryptographically verified.
- The adapter does not store secrets, GitHub access tokens, task-runner results, provider responses, or arbitrary payloads.
- Lifecycle events and grant events are append-only by convention, not tamper-evident against a database owner who can alter the file.
- Backups, restore drills, retention policy, database encryption at rest, operational metrics, and schema rollback policy remain production requirements.
- Atomic grant state and its audit row are guaranteed only when they use this one store/database transaction. An external audit system would require an outbox or another explicit consistency design.

## Verification

`tests/test_sqlite_persistence.py` covers migration versioning, restarts, same-version conflict, lifecycle state/audit atomicity, grant persistence, durable revocation, and rollback when grant or lifecycle audit insertion fails.

```sh
python -m unittest discover --start-directory tests --verbose
python scripts/validate_manifests.py
```
