"""Deterministic, host-owned task runner for bounded validation tasks.

This reference runner only exposes the built-in manifest validation task. It does
not import plugin modules, resolve user-provided entrypoints, perform network
requests, or execute third-party code.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Any, Callable, Mapping, Protocol

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


class TaskResultStore(Protocol):
    """Persistence contract for durable task results and run-ID idempotency."""

    @property
    def task_run_results(self) -> tuple[TaskResult, ...]:
        """Return completed results in stable run-ID order."""

    def get_task_run(self, run_id: str) -> tuple[str, TaskResult] | None:
        """Return stored request digest and result for a run ID, if present."""

    def save_task_run(self, request_digest: str, result: TaskResult) -> TaskResult:
        """Atomically create or return a prior result; reject run-ID conflicts."""


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
    """Execute only allowlisted, host-owned tasks and retain run evidence.

    Identical retries using the same run ID and envelope return the original
    result. Reusing a run ID for different context or content is rejected. An
    optional TaskResultStore provides cross-restart idempotency and durable
    results; the default remains process-local for lightweight tests.

    Successful invocation of the validator may produce valid=False; that is a
    completed validation task, not a task-runner failure.

    The input-size ceiling bounds the only currently supported task's workload.
    This class is not a sandbox, a process supervisor or a general execution
    runtime. An optional isolated validation mode starts the fixed, package-owned
    worker in a subprocess with a wall-clock timeout and POSIX CPU/address-space
    limits. That worker accepts only the schema-validation request protocol; it
    is not a general plugin sandbox or a facility for running arbitrary code.
    """

    def __init__(
        self,
        *,
        max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
        schema_path=DEFAULT_SCHEMA,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        store: TaskResultStore | None = None,
        isolated_validation: bool = False,
        worker_timeout_seconds: float = 5.0,
        worker_cpu_seconds: int = 2,
        worker_memory_mib: int = 256,
        worker_max_output_bytes: int = 1024 * 1024,
    ) -> None:
        if isinstance(max_input_bytes, bool) or not isinstance(max_input_bytes, int) or max_input_bytes < 1:
            raise ValueError("max_input_bytes must be a positive integer")
        if not isinstance(isolated_validation, bool):
            raise ValueError("isolated_validation must be a boolean")
        if (
            isinstance(worker_timeout_seconds, bool)
            or not isinstance(worker_timeout_seconds, (int, float))
            or not math.isfinite(worker_timeout_seconds)
            or worker_timeout_seconds <= 0
        ):
            raise ValueError("worker_timeout_seconds must be a positive number")
        if (
            isinstance(worker_cpu_seconds, bool)
            or not isinstance(worker_cpu_seconds, int)
            or worker_cpu_seconds < 1
        ):
            raise ValueError("worker_cpu_seconds must be a positive integer")
        if (
            isinstance(worker_memory_mib, bool)
            or not isinstance(worker_memory_mib, int)
            or worker_memory_mib < 64
        ):
            raise ValueError("worker_memory_mib must be an integer of at least 64 MiB")
        if (
            isinstance(worker_max_output_bytes, bool)
            or not isinstance(worker_max_output_bytes, int)
            or worker_max_output_bytes < 256
        ):
            raise ValueError("worker_max_output_bytes must be an integer of at least 256 bytes")
        self._max_input_bytes = max_input_bytes
        self._schema = load_schema(schema_path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or perf_counter
        self._store = store
        self._isolated_validation = isolated_validation
        self._worker_timeout_seconds = float(worker_timeout_seconds)
        self._worker_cpu_seconds = worker_cpu_seconds
        self._worker_memory_mib = worker_memory_mib
        self._worker_max_output_bytes = worker_max_output_bytes
        self._results: dict[str, tuple[str, TaskResult]] = {}
        self._lock = RLock()

    def _validate_manifest(self, manifest: Mapping[str, Any]) -> list[str]:
        """Validate in process by default or in the fixed isolated worker."""
        if not self._isolated_validation:
            return validate_manifest_data(manifest, self._schema)

        schema_bytes = _canonical_json(self._schema)
        request_payload = _canonical_json({"manifest": manifest, "schema": self._schema})
        max_request_bytes = self._max_input_bytes + len(schema_bytes) + 1024
        if len(request_payload) > max_request_bytes:
            raise TaskExecutionError(
                "worker-input-too-large",
                "Validation worker request exceeds the configured input bound.",
            )

        worker_path = Path(__file__).resolve().with_name("validation_worker.py")
        command = [
            sys.executable,
            "-I",
            "-B",
            str(worker_path),
            "--cpu-seconds",
            str(self._worker_cpu_seconds),
            "--memory-mib",
            str(self._worker_memory_mib),
            "--max-input-bytes",
            str(max_request_bytes),
            "--max-output-bytes",
            str(self._worker_max_output_bytes),
        ]
        try:
            with tempfile.TemporaryDirectory(prefix="loofy-validation-") as working_directory:
                completed = subprocess.run(
                    command,
                    input=request_payload,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=working_directory,
                    timeout=self._worker_timeout_seconds,
                    check=False,
                    close_fds=True,
                )
        except subprocess.TimeoutExpired as exc:
            raise TaskExecutionError(
                "task-timeout",
                "Manifest validation exceeded its wall-clock limit.",
            ) from exc
        except OSError as exc:
            raise TaskExecutionError(
                "worker-unavailable",
                "The isolated validation worker could not be started.",
            ) from exc

        if completed.returncode == 3:
            raise TaskExecutionError(
                "worker-output-too-large",
                "The isolated validation worker result exceeded the configured output bound.",
            )
        if completed.returncode == 4:
            raise TaskExecutionError(
                "worker-limits-unavailable",
                "The isolated validation worker could not apply required platform resource limits.",
            )
        if completed.returncode != 0:
            raise TaskExecutionError(
                "worker-failed",
                "The isolated validation worker failed without a valid result.",
            )
        if len(completed.stdout) > self._worker_max_output_bytes:
            raise TaskExecutionError(
                "worker-output-too-large",
                "The isolated validation worker result exceeded the configured output bound.",
            )
        try:
            response = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise TaskExecutionError(
                "worker-output-invalid",
                "The isolated validation worker returned an invalid response.",
            ) from exc
        if (
            not isinstance(response, dict)
            or not isinstance(response.get("valid"), bool)
            or not isinstance(response.get("errors"), list)
            or not all(isinstance(error, str) for error in response["errors"])
            or response["valid"] != (len(response["errors"]) == 0)
            or set(response) != {"valid", "errors"}
        ):
            raise TaskExecutionError(
                "worker-output-invalid",
                "The isolated validation worker returned an invalid response shape.",
            )
        return response["errors"]

    @property
    def supported_tasks(self) -> frozenset[str]:
        return SUPPORTED_TASKS

    @property
    def history(self) -> tuple[TaskResult, ...]:
        """Return recorded results in run-ID order."""
        if self._store is not None:
            return self._store.task_run_results
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

        # Validate the exact immutable-by-copy snapshot whose bytes are hashed;
        # do not re-read a caller-owned mutable mapping after computing its digest.
        normalized_manifest = json.loads(manifest_bytes.decode("utf-8"))
        request_document = {
            "run_id": run_id,
            "task_id": task_id,
            "actor_id": actor_id,
            "tenant_id": tenant_id,
            "resource_id": resource_id,
            "environment": environment,
            "manifest": normalized_manifest,
        }
        request_bytes = _canonical_json(request_document)
        request_digest = "sha256:" + hashlib.sha256(request_bytes).hexdigest()
        input_digest = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()

        # The SQLite store provides the cross-process final idempotency gate. The
        # local lock avoids duplicate work in the common same-runner case.
        with self._lock:
            if self._store is not None:
                existing_durable = self._store.get_task_run(run_id)
                if existing_durable is not None:
                    prior_digest, prior_result = existing_durable
                    if prior_digest != request_digest:
                        raise TaskRunConflictError(run_id)
                    return prior_result
            else:
                existing = self._results.get(run_id)
                if existing is not None:
                    prior_request_digest, prior_result = existing
                    if prior_request_digest != request_digest:
                        raise TaskRunConflictError(run_id)
                    return prior_result

            started_at = _aware_utc(self._clock(), "clock")
            start_tick = self._monotonic()
            errors = tuple(self._validate_manifest(normalized_manifest))
            valid = not errors
            output_bytes = _canonical_json({"valid": valid, "errors": errors})
            output_digest = "sha256:" + hashlib.sha256(output_bytes).hexdigest()
            completed_at = _aware_utc(self._clock(), "clock")
            elapsed = max(0.0, self._monotonic() - start_tick)

            metadata = normalized_manifest.get("metadata")
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
            if self._store is not None:
                # If another process raced this identical run ID, the store returns
                # the first committed result; different content raises a conflict.
                return self._store.save_task_run(request_digest, result)
            self._results[run_id] = (request_digest, result)
            return result
