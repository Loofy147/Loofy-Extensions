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
- A process-local history retains result/audit metadata, ordered by run ID for stable inspection. It is not durable.

## Resource bounds and explicit limitations

The runner limits manifest input size (default 256 KiB), rejects non-JSON values and unknown task IDs, and runs only one built-in schema-validation handler. This bounds the present task's input and accepted workload.

It does **not** yet enforce a hard preemptive timeout, OS-level CPU or memory quota, worker isolation, a durable audit sink, or a transactional run store. A synchronous Python function cannot be safely preempted by checking elapsed time afterward. Tasks that need those guarantees must run in a separate constrained worker before they are added to the allowlist.

## Host responsibilities

The caller must construct the envelope from authenticated host context and authorize access to the target resource before running the task. Recorded context fields are attribution only; they do not authenticate the actor. Production operation history requires durable storage, defined retention, access controls and an operation-boundary authorization check.

## Verification

Run the existing unit suite and manifest schema validator:

```sh
python -m unittest discover --start-directory tests --verbose
python scripts/validate_manifests.py
```

Tests cover valid and invalid manifests, attribution and digests, stable output identity, same-run retries, conflicting run IDs, unsupported task rejection, invalid JSON, missing context and the input-size limit.
