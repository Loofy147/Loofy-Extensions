# Reference Implementation Guide

## Purpose

The `loofy_extensions` package makes architecture decisions executable and testable. It includes in-memory examples and an optional transactional SQLite adapter. Neither is, by itself, a production plugin runtime or identity/authorization service.

## What is included

- `models.py`: immutable identifiers, extension record, lifecycle states, and audit-event value objects.
- `validation.py`: JSON Schema validation used by the CLI, registry and built-in validation task.
- `registry.py`: schema-backed registration, stable `(id, version)` identity, canonical manifest SHA-256, idempotent identical registration, and rejection of same-version content drift. An optional store can back registration and transitions.
- `lifecycle.py`: explicit allowed transitions, actor/reason requirements, approval evidence for approval and high-impact enablement, and audit-event generation.
- `policy.py`: exact-match, default-deny authorization for tenant, principal, extension version, capability, resource and environment; unexpired grants only; extra approval evidence for high-impact permissions.
- `grants.py`: grant issuance/revocation reference with host-supplied membership and scope-authority callbacks.
- `persistence.py`: versioned SQLite schema v3 for extension records, lifecycle events, grants, grant events, gateway operation audit events, and optional task-run results. State and paired lifecycle/grant audit events are committed atomically; task results and their request fingerprints are persisted transactionally.
- `providers/github_metadata.py` and `providers/github_gateway.py`: read-only GitHub metadata normalization and a host-side authorization/audit seam.
- `tasks.py`: allowlisted, input-bounded `manifest.validate` task; no third-party code execution. Task results can be held in memory or persisted through the SQLite store.
- `task_gateway.py`: host-side `AuthorizedTaskRunner` wrapper; replaces envelope attribution with trusted caller context, invokes an injected authorizer, and emits correlated audit events before/after the task.

## Quick in-memory example

~~~python
import json

from loofy_extensions import ExtensionRegistry
from loofy_extensions.validation import DEFAULT_EXAMPLES

registry = ExtensionRegistry()
manifest_path = next(DEFAULT_EXAMPLES.rglob("extension.json"))
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
record = registry.register(manifest)
print(record.key, record.state.value, record.manifest_digest)
~~~

## Durable local example

~~~python
from loofy_extensions import ExtensionRegistry, SQLiteStore, TaskRunner

with SQLiteStore("var/loofy-extensions.sqlite3") as store:
    registry = ExtensionRegistry(store=store)
    record = registry.register(manifest)
    runner = TaskRunner(store=store)
    result = runner.run(envelope)
~~~

For user-facing execution, wrap the runner with `AuthorizedTaskRunner`, and supply a `TaskCallerContext` derived from trusted host authentication and a host-owned `TaskAuthorizer`. Use the same `SQLiteStore` instance for registry operations, grant authority, gateway audit events, and durable task results when they need to share the same database. See [SQLite Persistence](sqlite-persistence.md) and [Authorized Task Runner](authorized-task-runner.md).

## Run checks

~~~sh
python -m pip install -r requirements-dev.txt
python -m unittest discover --start-directory tests --verbose
python scripts/validate_manifests.py
~~~

## Deliberate limitations

- Without a store, registry, grants, operation events, and task result history are process-local.
- SQLite state survives a process restart, but the reference database remains a local single-host store, not a distributed/high-availability system.
- The store does not authenticate the publisher or actor, mint credentials, receive webhooks, persist approval verification, or control an external API.
- Grant membership, grant-scope authority and caller context must come from trusted host services. Approval references are pointers, not cryptographically verified evidence.
- The task runner only exposes `manifest.validate`; it has no dynamic imports, hard preemptive timeout, OS-level resource limits, or worker isolation.
- The authorization wrapper does not authenticate `TaskCallerContext` or supply policy; host applications must enforce this.
- Schema-valid data is not proof of publisher authenticity, license compatibility, artifact safety or permission.
- A capability decision must never be trusted by itself for a consequential production side effect. The receiving API/service must authorize the real actor, tenant, target resource and environment again.

## Safe extension path

1. Keep registry validation and lifecycle rules independent of storage.
2. Add new schema changes as ordered migrations and test upgrade, rollback and restart behavior.
3. Bind approval evidence to the exact extension digest, principal, scope, action and expiry.
4. Wire host identity and policy services to grant issuance/revocation, task authorization and operation gateways.
5. Define access control, retention, backup and tamper-evidence for durable audit.
6. Add isolation and recovery evidence before third-party code execution.
