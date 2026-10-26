# Transactional SQLite Persistence Boundary

Status: local durable reference adapter. It persists extension state, grants, lifecycle/grant audit events, gateway operation audit events, and task-run results. It is not a distributed store or a production identity service.

## Design boundary

`SQLiteStore` implements the registry facade's storage contract, the grant-store operations consumed by `GrantAuthority`, the operation-audit sink consumed by `AuthorizedGitHubMetadataReader`, and the optional task-result store consumed by `TaskRunner`. One database file can therefore hold registry, grant, gateway-audit, and task-result state.

No third-party runtime dependency is required; the adapter uses Python's standard-library `sqlite3`.

## File permission handling

On POSIX hosts, the adapter creates a new database file with owner-only permissions (`0600`) before opening it and tightens an existing database file to `0600` before reading it. After WAL mode and schema initialization, the adapter also restricts any active WAL and shared-memory sidecar files to owner-only permissions. If the main database or sidecars are not regular files, initialization fails closed.

This reduces accidental local disclosure of tenant IDs, grants, authorization decisions, and audit metadata to other local users. It is not encryption at rest and does not replace directory permissions, OS account separation, secret management, or backup controls. The package applies these POSIX mode guarantees only on POSIX hosts; other platforms need an appropriate filesystem ACL policy.

## Schema migration

The database records applied versions in `schema_migrations`. Migrations are forward-only and applied under a write transaction. A database whose recorded version is newer than the code is rejected rather than silently rewritten.

Migration 1 creates:

- `extension_records`: immutable extension ID/version key, manifest digest, metadata, declared capability sets, lifecycle state, and UTC timestamps.
- `lifecycle_audit_events`: from/to state, actor, reason, approval reference, timestamp, and a foreign key to the extension version.
- `capability_grants`: exact tenant/principal/resource/environment scope, extension version, capability, grantor, expiry, approval reference, issuance time, and nullable revocation time.
- `grant_audit_events`: issued/revoked event detail with a foreign key to the grant.

Migration 2 creates:

- `operation_audit_events`: operation type, extension/version and manifest digest, principal, tenant, capability, resource, environment, outcome, decision/error code, timestamp, source ID when available, and a correlation ID.
- Indexes for tenant/resource/time queries and correlation-ID lookup.

Migration 3 creates:

- `task_runs`: run ID, canonical request digest, task and actor/tenant/resource/environment context, target extension version where present, outcome, validation errors, input/output digests, timestamps, and duration.
- Indexes for tenant/time queries and target extension lookup.

The v1→v3 and v2→v3 migration paths are tested. Migration 4 creates `audit_chain`, a single ordered SHA-256 hash chain over lifecycle, grant, and operation audit events, and backfills existing audit rows in deterministic timestamp/source order. New audit rows and their chain entries are committed in the same SQLite transaction. The verifier checks chain sequence, previous/event hashes, source references, and equality/counts against the underlying audit tables. Do not edit applied migrations in place; future schema changes must add a new ordered migration and test previous-schema upgrades and newer-schema rejection.

## Transaction guarantees

- Lifecycle transition: load current record, validate the transition, update state/timestamp, and insert its lifecycle event in one `BEGIN IMMEDIATE` transaction.
- Grant issuance: insert the immutable grant and issued event in one transaction. Identical retry is idempotent; reusing a grant ID with different content is a conflict.
- Grant revocation: set `revoked_at` and insert the revoked event in one transaction. Repeated revocation is rejected.
- Operation audit: each event and its hash-chain entry are appended in one transaction. The gateway writes the authorization decision before making the outbound request; if that insert fails, the provider is not called. Completion/failure events use the same correlation ID.
- Audit integrity: `verify_audit_chain()` detects modified/deleted/reordered chain rows and missing/altered audit source rows. It is a local integrity check, not a signature or an independent trust anchor.
- Task run result: the completed result and canonical request fingerprint are written in one transaction. A repeated run ID with the same fingerprint returns the first saved result; changed request content or scope produces a conflict even after the process restarts.
- Audit failure: lifecycle/grant state changes roll back when their paired audit-row insertion fails. Operation-audit append failures abort that append. Task results are not committed if result insertion fails.
- Concurrency: SQLite's writer lock and busy timeout serialize database writers. A competing identical task run may perform redundant pure validation work, but the final transaction returns the first result and prevents duplicate persisted identities. This is not a distributed task queue.

## Registry, gateway, and task integration

~~~python
from loofy_extensions import ExtensionRegistry, SQLiteStore, TaskRunner

with SQLiteStore("var/loofy-extensions.sqlite3") as store:
    registry = ExtensionRegistry(store=store)
    record = registry.register(manifest)
    runner = TaskRunner(store=store)
    result = runner.run(envelope)
~~~

Use the same live store instance for registry operations, grant issuance/revocation, gateway audit events, and durable task results when those records need one database and transaction domain. Close it during orderly shutdown.

## Important limitations

- Suitable as an embedded/local reference and single-host starting point; no multi-node coordination or high-availability guarantee is claimed.
- Caller identity, tenant membership, grantor authority, and approval verification must come from trusted host services.
- The local hash chain detects accidental or partial tampering, but a privileged actor able to rewrite the whole database can recompute it. Production still needs external immutable checkpoints or an independent append-only audit destination, audit access controls, retention, backup/restore, and monitoring.
- Grant and lifecycle event transaction guarantees apply within this database. Sending events to an external audit system requires an outbox or another explicit consistency design.
- Task execution results are stored only after task completion; this is not a queue, crash-recovery lease, or exactly-once execution engine. Current validation is pure/read-only, so retry is safe.
- This adapter does not store secrets, GitHub tokens, provider payloads, or task input manifests. It retains request fingerprints, result metadata, and validation error strings.

## Verification

`tests/test_sqlite_persistence.py` covers owner-only permissions on POSIX, v1→v3 and v2→v3 migrations, restart, lifecycle/grant/operation audit persistence, durable task results, immutable version/grant conflicts, future-schema rejection, and transactional rollback under forced audit failures. Task-runner tests cover cross-restart replay and conflicting run-ID reuse.

~~~sh
python -m unittest discover --start-directory tests --verbose
python scripts/validate_manifests.py
~~~
