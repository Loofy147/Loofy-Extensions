"""Tests for the allowlisted deterministic manifest-validation task runner."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

from loofy_extensions import SQLiteStore
from loofy_extensions.tasks import (
    ExecutionEnvelope,
    TaskExecutionError,
    TaskRunConflictError,
    TaskRunner,
)
from loofy_extensions.validation import DEFAULT_EXAMPLES


def sample_manifest() -> dict[str, object]:
    return json.loads(
        next(DEFAULT_EXAMPLES.rglob("extension.json")).read_text(encoding="utf-8")
    )


def envelope(
    manifest: dict[str, object] | None = None,
    *,
    run_id: str = "run-001",
    task_id: str = "manifest.validate",
    actor_id: str = "user:alice",
    tenant_id: str = "tenant:alpha",
) -> ExecutionEnvelope:
    return ExecutionEnvelope(
        run_id=run_id,
        task_id=task_id,
        actor_id=actor_id,
        tenant_id=tenant_id,
        resource_id="extension-candidate:example",
        environment="test",
        manifest=manifest if manifest is not None else sample_manifest(),
    )


class TaskRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock_tick = 0

        def clock():
            self.clock_tick += 1
            return datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc) + timedelta(
                milliseconds=self.clock_tick
            )

        self.mono_tick = 0.0

        def monotonic():
            self.mono_tick += 0.002
            return self.mono_tick

        self.runner = TaskRunner(clock=clock, monotonic=monotonic)

    def test_valid_manifest_returns_attributed_digest_result(self) -> None:
        result = self.runner.run(envelope())
        self.assertTrue(result.valid)
        self.assertEqual(result.outcome, "succeeded")
        self.assertEqual(result.task_id, "manifest.validate")
        self.assertEqual(result.actor_id, "user:alice")
        self.assertEqual(result.tenant_id, "tenant:alpha")
        self.assertEqual(result.target_extension_id, "com.loofy.extensions.manifest-validator")
        self.assertEqual(result.target_extension_version, "0.1.0")
        self.assertTrue(result.input_digest.startswith("sha256:"))
        self.assertTrue(result.output_digest.startswith("sha256:"))
        self.assertGreaterEqual(result.duration_ms, 0)
        self.assertEqual(len(self.runner.history), 1)

    def test_invalid_manifest_is_completed_validation_not_runner_failure(self) -> None:
        manifest = sample_manifest()
        del manifest["metadata"]["license"]
        result = self.runner.run(envelope(manifest))
        self.assertFalse(result.valid)
        self.assertEqual(result.outcome, "validation_failed")
        self.assertTrue(result.errors)
        self.assertEqual(len(self.runner.history), 1)

    def test_identical_run_id_and_request_return_cached_result(self) -> None:
        request = envelope()
        first = self.runner.run(request)
        retry = self.runner.run(request)
        self.assertIs(first, retry)
        self.assertEqual(len(self.runner.history), 1)

    def test_run_id_reuse_with_different_content_is_rejected(self) -> None:
        first = self.runner.run(envelope())
        changed = sample_manifest()
        changed["metadata"]["description"] = "Different payload"
        with self.assertRaises(TaskRunConflictError) as context:
            self.runner.run(envelope(changed, run_id=first.run_id))
        self.assertEqual(context.exception.code, "run-id-conflict")
        self.assertEqual(len(self.runner.history), 1)

    def test_run_id_reuse_across_different_actors_is_rejected(self) -> None:
        self.runner.run(envelope())
        with self.assertRaises(TaskRunConflictError):
            self.runner.run(envelope(actor_id="user:bob"))
        self.assertEqual(len(self.runner.history), 1)

    def test_unsupported_task_is_rejected_without_registration(self) -> None:
        with self.assertRaises(TaskExecutionError) as context:
            self.runner.run(envelope(task_id="arbitrary.plugin.entrypoint"))
        self.assertEqual(context.exception.code, "unsupported-task")
        self.assertEqual(self.runner.supported_tasks, frozenset({"manifest.validate"}))
        self.assertEqual(self.runner.history, ())

    def test_input_size_ceiling_is_enforced_before_validation(self) -> None:
        runner = TaskRunner(max_input_bytes=128)
        with self.assertRaises(TaskExecutionError) as context:
            runner.run(envelope())
        self.assertEqual(context.exception.code, "input-too-large")
        self.assertEqual(runner.history, ())

    def test_non_json_input_is_rejected(self) -> None:
        manifest = sample_manifest()
        manifest["runtime"]["bad_value"] = object()
        with self.assertRaises(TaskExecutionError) as context:
            self.runner.run(envelope(manifest))
        self.assertEqual(context.exception.code, "invalid-json-input")
        self.assertEqual(self.runner.history, ())

    def test_invalid_envelope_context_is_rejected(self) -> None:
        request = envelope(actor_id="   ")
        with self.assertRaises(TaskExecutionError) as context:
            self.runner.run(request)
        self.assertEqual(context.exception.code, "invalid-envelope")
        self.assertEqual(self.runner.history, ())

    def test_output_digest_for_same_manifest_is_stable_across_run_ids(self) -> None:
        first = self.runner.run(envelope(run_id="run-a"))
        second = self.runner.run(envelope(run_id="run-b"))
        self.assertEqual(first.input_digest, second.input_digest)
        self.assertEqual(first.output_digest, second.output_digest)

    def test_durable_result_survives_restart_and_run_id_conflicts_persist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "task-runs.sqlite3"
            store = SQLiteStore(database_path)
            runner = TaskRunner(
                store=store,
                clock=lambda: datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc),
                monotonic=lambda: 1.0,
            )
            request = envelope(run_id="durable-run-001")
            try:
                first = runner.run(request)
                self.assertEqual(runner.history, (first,))
                store.close()

                reopened_store = SQLiteStore(database_path)
                try:
                    reopened_runner = TaskRunner(
                        store=reopened_store,
                        clock=lambda: datetime(2027, 10, 25, 4, 0, tzinfo=timezone.utc),
                        monotonic=lambda: 10.0,
                    )
                    retried = reopened_runner.run(request)
                    self.assertEqual(retried, first)
                    self.assertEqual(reopened_runner.history, (first,))

                    changed_manifest = sample_manifest()
                    changed_manifest["metadata"]["description"] = "different payload after restart"
                    with self.assertRaises(TaskRunConflictError) as context:
                        reopened_runner.run(
                            envelope(changed_manifest, run_id="durable-run-001")
                        )
                    self.assertEqual(context.exception.code, "run-id-conflict")
                    self.assertEqual(reopened_runner.history, (first,))
                finally:
                    reopened_store.close()
            finally:
                store.close()

    def test_invalid_manifest_result_is_persisted_as_completed_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = SQLiteStore(Path(temporary_directory) / "invalid-task.sqlite3")
            try:
                invalid = sample_manifest()
                del invalid["metadata"]["license"]
                runner = TaskRunner(store=store)
                result = runner.run(envelope(invalid, run_id="invalid-run"))
                self.assertFalse(result.valid)
                self.assertEqual(result.outcome, "validation_failed")
                self.assertTrue(result.errors)
                self.assertEqual(runner.history, (result,))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
