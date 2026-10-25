"""Deterministic, host-owned task runner for bounded validation tasks.

This reference runner only exposes the built-in manifest validation task. It does
not import plugin modules, resolve user-provided entrypoints, perform network
requests, or execute third-party code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from time import perf_counter
from typing import Any, Callable, Mapping

from .validation import DEFAULT_SCHEMA, load_schema, validate_manifest_data


SUPPORTED_TASKS = frozenset({"manifest.validate"})
DEFAULT_MAX_INPUT_BYTES = 256 * 1024


class TaskExecutionError(ValueError):
    """Stable error raised when a task request cannot safely be accepted."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class TaskRunConflictError(TaskExecutionError):
    """Raised when a run ID is reused with different request content."""

    def __init__(self, run_id: str) -> None:
        super().__init__(
            "run-id-conflict",
            f"Run ID {run_id!r} already exists with different request content.",
        )


@dataclass(frozen=True)
class ExecutionEnvelope:
    """Host-created execution request with explicit identity and resource scope."""

    run_id: str
    task_id: str
    actor_id: str
    tenant_id: str
    resource_id: str
    environment: str
    manifest: Mapping[str, Any]


@dataclass(frozen=True)
class TaskResult:
    """Immutable run result with content digests and operation attribution."""

    run_id: str
    task_id: str
    actor_id: str
    tenant_id: str
    resource_id: str
    environment: str
    target_extension_id: str | None
    target_extension_version: str | None
    outcome: str
    valid: bool
    errors: tuple[str, ...]
    input_digest: str
    output_digest: str
    started_at: datetime
    completed_at: datetime
    duration_ms: float


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise TaskExecutionError(
            "invalid-json-input",
            "Task input must contain only JSON-compatible values.",
        ) from exc


def _nonblank(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskExecutionError("invalid-envelope", f"{field} must be a non-empty string.")
    return value.strip()


def _aware_utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TaskExecutionError("invalid-clock", f"{field} must be a timezone-aware datetime.")
    return value.astimezone(timezone.utc)


class TaskRunner:
    """Execute only allowlisted, host-owned tasks and retain in-memory run evidence.

    Identical retries using the same run ID and envelope return the original
    result. Reusing a run ID for different context or content is rejected.
    Successful invocation of the validator may produce `valid=False`; that is
    a completed validation task, not a task-runner failure.

    The input-size ceiling bounds the only currently supported task's workload.
    This class is not a sandbox, a process supervisor or a general execution
    runtime; tasks that need hard preemptive time/memory limits require a separate
    isolated worker design.
    """

    def __init__(
        self,
        *,
        max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
        schema_path=DEFAULT_SCHEMA,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if isinstance(max_input_bytes, bool) or not isinstance(max_input_bytes, int) or max_input_bytes < 1:
            raise ValueError("max_input_bytes must be a positive integer")
        self._max_input_bytes = max_input_bytes
        self._schema = load_schema(schema_path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or perf_counter
        self._results: dict[str, tuple[str, TaskResult]] = {}
        self._lock = RLock()

    @property
    def supported_tasks(self) -> frozenset[str]:
        return SUPPORTED_TASKS

    @property
    def history(self) -> tuple[TaskResult, ...]:
        """Return recorded results in run-ID order; process-local and non-durable."""
        with self._lock:
            return tuple(self._results[run_id][1] for run_id in sorted(self._results))

    def run(self, envelope: ExecutionEnvelope) -> TaskResult:
        """Run a single built-in task after validating its envelope and input."""
        if not isinstance(envelope, ExecutionEnvelope):
            raise TaskExecutionError("invalid-envelope", "A typed ExecutionEnvelope is required.")

        run_id = _nonblank(envelope.run_id, "run_id")
        task_id = _nonblank(envelope.task_id, "task_id")
        actor_id = _nonblank(envelope.actor_id, "actor_id")
        tenant_id = _nonblank(envelope.tenant_id, "tenant_id")
        resource_id = _nonblank(envelope.resource_id, "resource_id")
        environment = _nonblank(envelope.environment, "environment")
        if task_id not in SUPPORTED_TASKS:
            raise TaskExecutionError("unsupported-task", "The requested task is not in the host-owned allowlist.")
        if not isinstance(envelope.manifest, Mapping):
            raise TaskExecutionError("invalid-json-input", "Manifest task input must be a JSON object.")

        manifest_bytes = _canonical_json(dict(envelope.manifest))
        if len(manifest_bytes) > self._max_input_bytes:
            raise TaskExecutionError(
                "input-too-large",
                f"Manifest input exceeds the {self._max_input_bytes}-byte limit.",
            )

        request_document = {
            "run_id": run_id,
            "task_id": task_id,
            "actor_id": actor_id,
            "tenant_id": tenant_id,
            "resource_id": resource_id,
            "environment": environment,
            "manifest": dict(envelope.manifest),
        }
        request_bytes = _canonical_json(request_document)
        request_digest = "sha256:" + hashlib.sha256(request_bytes).hexdigest()
        input_digest = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()

        # Serialize same-process runs: duplicate IDs cannot race into duplicate work.
        with self._lock:
            existing = self._results.get(run_id)
            if existing is not None:
                prior_request_digest, prior_result = existing
                if prior_request_digest != request_digest:
                    raise TaskRunConflictError(run_id)
                return prior_result

            started_at = _aware_utc(self._clock(), "clock")
            start_tick = self._monotonic()
            errors = tuple(validate_manifest_data(dict(envelope.manifest), self._schema))
            valid = not errors
            output_bytes = _canonical_json({"valid": valid, "errors": errors})
            output_digest = "sha256:" + hashlib.sha256(output_bytes).hexdigest()
            completed_at = _aware_utc(self._clock(), "clock")
            elapsed = max(0.0, self._monotonic() - start_tick)

            metadata = envelope.manifest.get("metadata")
            metadata = metadata if isinstance(metadata, Mapping) else {}
            extension_id = metadata.get("id")
            version = metadata.get("version")
            if not isinstance(extension_id, str) or not extension_id.strip():
                extension_id = None
            if not isinstance(version, str) or not version.strip():
                version = None

            result = TaskResult(
                run_id=run_id,
                task_id=task_id,
                actor_id=actor_id,
                tenant_id=tenant_id,
                resource_id=resource_id,
                environment=environment,
                target_extension_id=extension_id,
                target_extension_version=version,
                outcome="succeeded" if valid else "validation_failed",
                valid=valid,
                errors=errors,
                input_digest=input_digest,
                output_digest=output_digest,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=round(elapsed * 1000, 3),
            )
            self._results[run_id] = (request_digest, result)
            return result
