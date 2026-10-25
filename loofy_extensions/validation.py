"""Shared JSON Schema loading and manifest validation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = REPOSITORY_ROOT / "schemas" / "extension-manifest.schema.json"
DEFAULT_EXAMPLES = REPOSITORY_ROOT / "examples" / "extensions"


def load_schema(schema_path: Path = DEFAULT_SCHEMA) -> dict[str, Any]:
    """Load and meta-validate the extension schema."""
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read schema {schema_path}: {exc}") from exc

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"Schema is not valid JSON Schema Draft 2020-12: {exc.message}") from exc
    return schema


def validate_manifest_data(
    instance: Any,
    schema: dict[str, Any],
    *,
    label: str = "<manifest>",
) -> list[str]:
    """Validate an already parsed JSON value and return deterministic errors."""
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
        messages.append(f"{label}:{location}: {error.message}")
    return messages


def validate_manifest_file(
    manifest_path: Path,
    schema: dict[str, Any],
) -> list[str]:
    """Read a UTF-8 JSON file and validate its contents."""
    try:
        instance = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"{manifest_path}: could not read valid JSON: {exc}"]
    return validate_manifest_data(instance, schema, label=str(manifest_path))


def discover_manifests(directory: Path = DEFAULT_EXAMPLES) -> list[Path]:
    """Discover extension.json examples without treating the schema as a manifest."""
    if not directory.exists():
        return []
    return sorted(directory.rglob("extension.json"))
