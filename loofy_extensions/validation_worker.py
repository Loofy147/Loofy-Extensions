"""Fixed subprocess worker for the built-in manifest validation task.

This entrypoint only implements JSON Schema validation. It never imports a
manifest entrypoint, loads candidate code, opens network connections, or accepts
a script/module/path from the request. It is started by TaskRunner using Python
isolated mode and applies POSIX process resource limits before parsing payloads.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _apply_resource_limits(cpu_seconds: int, memory_mib: int) -> bool:
    """Apply fail-closed limits on POSIX; return False if unavailable/failed."""
    if os.name != "posix":
        return True
    try:
        import resource

        resource.setrlimit(
            resource.RLIMIT_CPU,
            (cpu_seconds, cpu_seconds + 1),
        )
        if not hasattr(resource, "RLIMIT_AS"):
            return False
        memory_bytes = memory_mib * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        if hasattr(resource, "RLIMIT_CORE"):
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, OSError, ValueError):
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cpu-seconds", required=True, type=_positive_integer)
    parser.add_argument("--memory-mib", required=True, type=_positive_integer)
    parser.add_argument("--max-input-bytes", required=True, type=_positive_integer)
    parser.add_argument("--max-output-bytes", required=True, type=_positive_integer)
    try:
        arguments = parser.parse_args()
    except SystemExit:
        return 2

    if arguments.memory_mib < 64 or arguments.max_output_bytes < 256:
        return 2
    if not _apply_resource_limits(arguments.cpu_seconds, arguments.memory_mib):
        sys.stderr.write("required resource limits unavailable\n")
        return 4

    payload_bytes = sys.stdin.buffer.read(arguments.max_input_bytes + 1)
    if len(payload_bytes) > arguments.max_input_bytes:
        sys.stderr.write("worker input limit exceeded\n")
        return 2
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        sys.stderr.write("worker input is not valid JSON\n")
        return 2
    if (
        not isinstance(payload, dict)
        or set(payload) != {"manifest", "schema"}
        or not isinstance(payload["manifest"], dict)
        or not isinstance(payload["schema"], dict)
    ):
        sys.stderr.write("worker input does not match the validation protocol\n")
        return 2

    # Python isolated mode intentionally excludes the project from sys.path.
    # Add only this installed/package directory; never derive import paths from
    # fields in the request payload.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from validation import validate_manifest_data

        errors = validate_manifest_data(payload["manifest"], payload["schema"])
        response = {
            "valid": len(errors) == 0,
            "errors": errors,
        }
        output = json.dumps(
            response,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except Exception:
        # Stable external error only; don't echo input or internal exception text.
        sys.stderr.write("worker validation failed\n")
        return 2

    if len(output) > arguments.max_output_bytes:
        sys.stderr.write("worker output limit exceeded\n")
        return 3
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
