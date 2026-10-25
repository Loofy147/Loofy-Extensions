# Security Policy

## Current status

This repository currently contains architecture documents, a JSON Schema contract, example metadata, and validation code. It does not yet provide a production extension runtime or credential-handling service.

## Reporting a vulnerability

Do not disclose credentials, exploit details, or unpatched vulnerabilities in a public issue or pull request. Use GitHub's private vulnerability reporting / Security Advisories feature for this repository when available. If private reporting is unavailable, contact the maintainer through a private GitHub channel and include only the information needed to establish impact and reproduce safely.

## Scope priorities

High-priority reports include:
- Authorization bypass or capability escalation.
- Cross-repository or cross-tenant data access.
- Secret disclosure or credential misuse.
- Manifest parsing that leads to unsafe execution.
- Webhook spoofing/replay that can cause unauthorized side effects.
- Supply-chain or workflow changes that expose credentials or execute untrusted code.

## Safe design expectations

- Default deny for capabilities and network egress.
- Never place raw secret values in manifests, example files, test fixtures, logs, or issue comments.
- Treat manifests and extension output as untrusted input.
- Pin workflow dependencies to verified full commit SHAs unless a trusted dependency lockfile provides stronger enforcement.
- Keep privileged writes and third-party executable work disabled until policy, isolation, and audit controls are implemented.
