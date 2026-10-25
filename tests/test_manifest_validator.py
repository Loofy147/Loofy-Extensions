"""Unit tests for the extension manifest contract validator."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_manifests import (
    DEFAULT_EXAMPLES,
    DEFAULT_SCHEMA,
    load_schema,
    validate_manifest,
)


class ManifestValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = load_schema(DEFAULT_SCHEMA)
        cls.sample_path = next(DEFAULT_EXAMPLES.rglob("extension.json"))
        cls.sample = json.loads(cls.sample_path.read_text(encoding="utf-8"))

    def test_reference_manifest_is_valid(self) -> None:
        self.assertEqual(validate_manifest(self.sample_path, self.schema), [])

    def test_missing_required_metadata_is_rejected(self) -> None:
        manifest = copy.deepcopy(self.sample)
        del manifest["metadata"]["publisher"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "extension.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            errors = validate_manifest(path, self.schema)
        self.assertTrue(any("publisher" in error for error in errors))

    def test_unknown_top_level_field_is_rejected(self) -> None:
        manifest = copy.deepcopy(self.sample)
        manifest["permissions"]["admin"] = True
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "extension.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            errors = validate_manifest(path, self.schema)
        self.assertTrue(any("Additional properties are not allowed" in error for error in errors))

    def test_raw_secret_value_is_not_a_valid_secret_reference(self) -> None:
        manifest = copy.deepcopy(self.sample)
        manifest["secrets"] = {
            "references": [
                {
                    "name": "github-token",
                    "vaultRef": "vault://team/github",
                    "scope": "repository:read",
                    "value": "must-not-be-supported"
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "extension.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            errors = validate_manifest(path, self.schema)
        self.assertTrue(any("value" in error for error in errors))

    def test_write_capability_does_not_appear_in_example(self) -> None:
        self.assertEqual(self.sample["approval"]["writeOperations"], "none")
        self.assertTrue(
            all("write" not in capability for capability in self.sample["permissions"]["requested"])
        )


if __name__ == "__main__":
    unittest.main()
