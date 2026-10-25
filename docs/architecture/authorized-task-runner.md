# Authorized Task Runner Boundary

Status: host-side reference wrapper for the built-in manifest validation task. It does not authenticate users or implement an identity/policy service.

## Flow

The wrapper takes a typed task envelope and a separate `TaskCallerContext`. That context must be constructed by the host authentication layer. Before calling the task runner, it overwrites the envelope's actor, tenant, and environment fields with that context. Values supplied in those envelope fields cannot influence authorization or task-result attribution.

The wrapper asks the injected `TaskAuthorizer` to authorize the principal, tenant, task ID, resource and environment against current host policy. The package includes `CapabilityTaskAuthorizer`, which maps the allowlisted `manifest.validate` task to `task.manifest.validate` and calls the existing exact-match, tenant-scoped `authorize()` policy using record and active-grant loaders. It only accepts an explicit typed decision. A denied decision, malformed decision, or policy callback failure does not run the task. Policy lookup failures are converted to a stable denial rather than exposing internal exception details.

The wrapper writes an authorization event to the supplied operation-audit sink before running the task. If that append fails, the task is not invoked. Completion, validation failure, and task errors are then recorded under the same correlation ID (the validated run ID). The SQLite store can be used as the sink, so authorization and outcome events survive a restart.

## Contract

- Only task IDs advertised by the wrapped runner are allowed; currently that is `manifest.validate`.
- The target resource is part of the authorization callback input, not evidence that the caller owns that resource.
- Task actor, tenant and environment attribution come from `TaskCallerContext`, not from the untrusted envelope.
- The operation uses capability name `task.manifest.validate`.
- The audit event records decision/outcome, caller and tenant, resource, environment, input digest when the task result is available, and correlation ID. It never records the raw manifest.
- Pre-run audit failure blocks execution; a post-run audit failure may cause the caller to observe an error even though the pure validation result is already persisted. Retrying the same run ID returns the persisted result and writes another correlated outcome event if the sink becomes available.

## Example wiring

~~~python
from loofy_extensions import (
    AuthorizedTaskRunner,
    CapabilityTaskAuthorizer,
    ExtensionKey,
    ExtensionRegistry,
    SQLiteStore,
    TaskRunner,
)

with SQLiteStore("var/loofy-extensions.sqlite3") as store:
    registry = ExtensionRegistry(store=store)
    task_key = ExtensionKey("com.loofy.extensions.task-runner", "1.0.0")
    authorizer = CapabilityTaskAuthorizer(
        extension_key=task_key,
        record_loader=lambda key: registry.get(key.extension_id, key.version),
        grants_loader=store.active_grants,
    )
    runner = TaskRunner(store=store, isolated_validation=True)
    authorized_runner = AuthorizedTaskRunner(
        runner,
        authorizer=authorizer,
        audit_sink=store,
    )
    # caller_context must be produced by host authentication.
    result = authorized_runner.run(envelope, caller=caller_context)
~~~

The canonical host-owned contract is `examples/extensions/task-runner/extension.json`. Register it through the normal registry API and transition its record through the lifecycle to `enabled` before authorizing tasks. The record must request the capability `task.manifest.validate`. Grant creation still goes through `GrantAuthority` with host-verified tenant membership and grant-scope authority. Record/grant loaders must be current and authoritative; this adapter does not authenticate callers or issue grants.

## Boundaries still outstanding

- The core `TaskRunner` remains directly callable for tests and trusted internal use. Applications exposed to users should expose `AuthorizedTaskRunner` or an equivalent host authorization boundary, not the bare runner.
- The wrapper cannot authenticate `TaskCallerContext`; callers must prevent end users from constructing or modifying it.
- `CapabilityTaskAuthorizer` reuses the existing grant evaluator but does not provision grants, manage memberships, authenticate callers, or verify approval references.
- SQLite audit rows are durable but not tamper-evident and still need production access control, retention, backup and monitoring.
- The isolated validator worker has a wall-clock timeout and POSIX CPU/address-space limits, but is not a network sandbox or general-purpose plugin sandbox; queue supervision remains deferred.

## Tests

The task-gateway suite covers untrusted envelope identity being overridden, allow/deny outcomes, missing authorization context, unsupported task IDs, input-size errors, audit-before-run behavior, and durable audit/result recovery with SQLite.
