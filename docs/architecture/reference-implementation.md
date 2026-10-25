# Reference Implementation Guide

## Purpose

The `loofy_extensions` package makes a few architecture decisions executable and testable. It is deliberately an in-memory reference implementation, not a production service or extension loader.

## What is included

- `models.py`: immutable identifiers, extension record, lifecycle states, and audit-event value objects.
- `validation.py`: JSON Schema validation used by both the CLI and registry.
- `registry.py`: schema-backed registration, stable `(id, version)` identity, canonical manifest SHA-256, idempotent identical registration, and rejection of same-version content drift.
- `lifecycle.py`: explicit allowed transitions, actor/reason requirements, approval evidence for approval and high-impact enablement, and audit-event generation.
- `policy.py`: exact-match, default-deny authorization for principal, extension version, capability, resource, and environment; unexpired grants only; extra approval evidence for high-impact permissions.

## Quick example

```python
import json
from pathlib import Path

from loofy_extensions import ExtensionRegistry
from loofy_extensions.validation import DEFAULT_EXAMPLES

registry = ExtensionRegistry()
manifest_path = next(DEFAULT_EXAMPLES.rglob("extension.json"))
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

record = registry.register(manifest)
print(record.key, record.state.value, record.manifest_digest)
```

Run all tests and validate the sample:

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover --start-directory tests --verbose
python scripts/validate_manifests.py
```

## Deliberate limitations

- State and audit events live only in the process memory and disappear at restart.
- The lock protects this Python process only; it is not a distributed transaction or database concurrency control.
- The module does not contact GitHub, validate a publisher signature, run code, mint credentials, receive webhooks, persist approvals, or control the external API.
- The grant objects are supplied by the caller. No grant-issuance workflow, durable revocation service, tenant-bound store, or identity provider exists yet.
- Schema-valid data is not proof of publisher authenticity, license compatibility, artifact safety, or permission.
- A capability decision must never be trusted by itself for a consequential production side effect. The receiving API/service must authorize the real actor, target resource, tenant and environment again.

## Safe extension path

1. Keep the registry interface independent of persistence.
2. Add a transactional storage adapter and migration tests.
3. Bind approval evidence to the exact extension digest, principal, scope, action and expiry.
4. Add operation-boundary policy checks and short-lived credentials.
5. Add read-only provider contract tests before introducing write operations.
6. Add durable audit, revocation, isolation, and recovery evidence before third-party code execution.
