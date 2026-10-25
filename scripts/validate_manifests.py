#!/usr/bin/env python3
"""Validate example extension manifests against the repository JSON Schema."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = REPOSITORY_ROOT / "schemas" / "extension-manifest.schema.json"
DEFAULT_EXAMPLES = REPOSITORY_ROOT / "examples" / "extensions"


def load_schema(schema_path: Path) -> dict[str, Any]:
    """Load and validate the schema itself before validating any manifest."""
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read schema {schema_path}: {exc}") from exc

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"Schema is not valid JSON Schema Draft 2020-12: {exc.message}") from exc
    return schema


def validate_manifest(
    manifest_path: Path,
    schema: dict[str, Any],
) -> list[str]:
    """Return human-readable validation errors; an empty list means success."""
    try:
        instance = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"{manifest_path}: could not read valid JSON: {exc}"]

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(instance),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    messages: list[str] = []
    for error in errors:
        location = "$"
        for part in error.absolute_path:
            location += f"[{part}]" if isinstance(part, int) else f".{part}"
        messages.append(f"{manifest_path}:{location}: {error.message}")
    return messages


def discover_manifests(directory: Path) -> list[Path]:
    """Find contract examples without accidentally treating the schema as a manifest."""
    if not directory.exists():
        return []
    return sorted(directory.rglob("extension.json"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA,
        help="Path to the JSON Schema.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        action="append",
        help="Validate a specific manifest; may be repeated. Defaults to the examples tree.",
    )
    args = parser.parse_args()

    try:
        schema = load_schema(args.schema)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    manifests = args.manifest or discover_manifests(DEFAULT_EXAMPLES)
    if not manifests:
        print("ERROR: no extension manifests were found.", file=sys.stderr)
        return 2

    failures = 0
    for manifest in manifests:
        errors = validate_manifest(manifest, schema)
        if errors:
            failures += 1
            print(f"FAIL {manifest}")
            for error in errors:
                print(f"  {error}")
        else:
            print(f"PASS {manifest}")

    if failures:
        print(f"Validation failed: {failures} of {len(manifests)} manifest(s) invalid.")
        return 1

    print(f"Validation passed: {len(manifests)} manifest(s) valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
