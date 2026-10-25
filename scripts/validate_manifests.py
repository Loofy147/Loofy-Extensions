#!/usr/bin/env python3
"""Validate example extension manifests against the repository JSON Schema."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loofy_extensions.validation import (
    DEFAULT_EXAMPLES,
    DEFAULT_SCHEMA,
    discover_manifests,
    load_schema,
    validate_manifest_file,
)


def validate_manifest(manifest_path: Path, schema: dict) -> list[str]:
    """Compatibility wrapper used by the test suite and CLI."""
    return validate_manifest_file(manifest_path, schema)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA, help="Path to the JSON Schema.")
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
        errors = validate_manifest_file(manifest, schema)
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
