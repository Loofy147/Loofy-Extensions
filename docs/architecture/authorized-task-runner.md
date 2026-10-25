# Authorized Task Runner Boundary

Status: host-side reference wrapper for the built-in manifest validation task. It does not authenticate users or implement an identity/policy service.

## Flow

The wrapper takes a typed task envelope and a separate `TaskCallerContext`. That context must be constructed by the host authentication layer. Before calling the task runner, it overwrites the envelope's actor, tenant, and environment fields with that context. Values supplied in those envelope fields cannot influence authorization or task-result attribution.

The wrapper asks the injected `TaskAuthorizer` to authorize the principal, tenant, task ID, resource and environment against current host policy. It only accepts an explicit typed decision. A denied decision, malformed decision, or policy callback failure does not run the task. Policy lookup failures are converted to a stable denial rather than exposing internal exception details.

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
    SQLiteStore,
    TaskRunner,
)

with SQLiteStore("var/loofy-extensions.sqlite3") as store:
    runner = TaskRunner(store=store)
    authorized_runner = AuthorizedTaskRunner(
        runner,
        authorizer=host_task_authorizer,
        audit_sink=store,
    )
    # caller_context must be produced by host authentication.
    result = authorized_runner.run(envelope, caller=caller_context)
~~~

`host_task_authorizer` is a host-owned implementation satisfying the `TaskAuthorizer` contract; it is deliberately not invented or supplied by this package. A production adapter must resolve authenticated identity, tenant membership and task/resource policy from authoritative sources.

## Boundaries still outstanding

- The core `TaskRunner` remains directly callable for tests and trusted internal use. Applications exposed to users should expose `AuthorizedTaskRunner` or an equivalent host authorization boundary, not the bare runner.
- The wrapper cannot authenticate `TaskCallerContext`; callers must prevent end users from constructing or modifying it.
- The reference wrapper does not provision policy grants, manage memberships, verify approvals, or supply a durable policy engine.
- SQLite audit rows are durable but not tamper-evident and still need production access control, retention, backup and monitoring.
- The runner still has no hard preemptive timeout, OS-level CPU/memory quotas, worker isolation, or queue supervision.

## Tests

The task-gateway suite covers untrusted envelope identity being overridden, allow/deny outcomes, missing authorization context, unsupported task IDs, input-size errors, audit-before-run behavior, and durable audit/result recovery with SQLite.
