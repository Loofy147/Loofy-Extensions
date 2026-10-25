# Deterministic Manifest Validation Task Runner

Status: first bounded host-owned task implementation. It is a pure in-process reference task, not a general plugin runtime or isolated worker.

## Supported task

Only `manifest.validate` is exposed. The runner does not resolve manifest entrypoints, dynamically import extension modules, make network requests, or execute third-party code. It parses a canonical snapshot of the submitted manifest and validates it against the repository's versioned JSON Schema.

## Execution envelope

Each request requires a run ID, task ID, actor, tenant, resource, environment and manifest JSON object. The result records the request context, target extension ID/version where present, validation outcome, errors, input digest, output digest, start/completion times and duration.

Canonical JSON serialization and SHA-256 digests give a stable identity to the exact manifest snapshot that was validated. The task validates that same snapshot, rather than rereading a caller-owned mutable mapping after hashing it.

## Determinism and retry handling

- Identical requests with the same run ID return the first recorded result without rerunning the task.
- Reusing a run ID with different input or caller/scope context is rejected with `run-id-conflict`.
- The output digest covers the deterministic validation result (`valid` and ordered schema errors); it is independent of timestamps and duration.
- Invalid manifest content is a normal validation outcome (`validation_failed`), distinct from runner rejection or execution errors.
- Run history is process-local by default. When a `TaskResultStore` is injected, result records and their canonical request fingerprints survive process restarts.

## Optional durable result storage

Construct `TaskRunner(store=sqlite_store)` with the same `SQLiteStore` used by the registry and grant services. The runner consults the stored request fingerprint before doing work and persists the first completed result with its fingerprint transactionally.

- An identical request with the same run ID returns the original persisted result, including the original timing metadata.
- A different request context or manifest using that run ID raises `TaskRunConflictError`, including after restart.
- When concurrent runner instances race on the same run ID, SQLite's final write transaction selects one persisted result; any identical retry receives that result. Changed content conflicts.
- Results store metadata, digests and validation errors, not the input manifest itself.

Because the task only validates input and has no side effects, redundant validation under a rare multi-instance race is safe. This does not provide a general exactly-once execution guarantee for future side-effecting tasks.

## Authorization and audit boundary

Applications exposed to users should wrap the bare runner in `AuthorizedTaskRunner`. It accepts `TaskCallerContext` from the host authentication layer and overwrites actor, tenant, and environment fields in the task envelope before authorization or execution. The injected `TaskAuthorizer` receives the principal, tenant, task ID, resource and environment. A denial, invalid decision, or policy callback failure prevents the task from running.

The wrapper writes an authorization event before execution and records success, validation failure, or task error with the same correlation ID (the validated run ID). If the pre-run audit append fails, the task is not invoked. The SQLite store can serve as the audit sink and preserves these events across restarts.

This wrapper does not authenticate caller context and does not implement policy decisions. The application must construct caller context from trusted authentication and bind the authorizer to current authoritative membership and resource policy. Do not expose the bare `TaskRunner` to untrusted callers.

## Resource bounds and explicit limitations

The runner limits manifest input size (default 256 KiB), rejects non-JSON values and unknown task IDs, and runs only one built-in schema-validation handler. This bounds the present task's input and accepted workload.

It does **not** yet enforce a hard preemptive timeout, OS-level CPU or memory quota, worker isolation, or queue supervision. A synchronous Python function cannot be safely preempted by checking elapsed time afterward. Tasks that need those guarantees must run in a separate constrained worker before they are added to the allowlist.

## Verification

Run the existing unit suite and manifest schema validator:

~~~sh
python -m unittest discover --start-directory tests --verbose
python scripts/validate_manifests.py
~~~

Tests cover valid and invalid manifests, attribution and digests, same-run retries, conflicting run IDs, unsupported task rejection, input limits, durable result replay, caller-context override, policy denial/failure, audit-before-run behavior, and correlated operation events.
