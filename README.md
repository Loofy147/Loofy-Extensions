# Loofy Extensions

A governed foundation for discovering, describing, validating, and eventually executing extensions across developer tools and connected services.

> Status: contract and governance foundation. This repository does not yet implement a general-purpose plugin runtime, credential vault, scheduler, queue, sandbox, or extension marketplace.

## What this repository establishes

- A versioned JSON manifest contract for different extension types.
- Explicit requested capabilities, runtime/network constraints, secret references, and approval policy.
- A validator and automated checks for the manifest examples.
- Architecture, trust boundaries, threat model, contribution policy, and a phased implementation plan.

## Core principle

A manifest declares what an extension claims to provide and what access it requests. **It does not grant permissions.** Installation, approval, authorization, and runtime enforcement must remain separate controls.

## Extension types

| Type | Best fit |
| --- | --- |
| GitHub App / hosted service | Persistent event-driven integration, synchronization, dashboards, external state |
| GitHub Action | Bounded task within a CI workflow |
| Reusable workflow | Versioned multi-job orchestration and shared pipeline policy |
| Provider / adapter | One host-owned contract implemented for a specific vendor |
| MCP server / tool package | Typed operations available to assistant or workflow clients |
| UI extension | Navigation, inspection, configuration, or focused user interaction |
| Declarative extension | Metadata, rules, and configuration with no arbitrary code execution |
| Sandboxed artifact | Selected third-party executable workload behind isolation and review |

See docs/architecture/extension-types.md and docs/architecture/reference-architecture.md.

## Validate locally

Python 3.12 or newer is recommended.

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover --start-directory tests --verbose
python scripts/validate_manifests.py
```

The GitHub Actions workflow runs the same checks for pull requests and pushes to main.

## Initial boundaries

The first milestone is intentionally limited to contracts and validation. The repository should not store credentials or accept arbitrary third-party execution until authorization, lifecycle, isolation, provenance, and audit designs have been implemented and tested.

## Documentation

- Architecture: docs/architecture/reference-architecture.md
- Extension type taxonomy: docs/architecture/extension-types.md
- First architecture decision: docs/architecture/decisions/0001-extension-boundaries.md
- Threat model: docs/security/threat-model.md
- Implementation sequence: docs/roadmap/implementation-plan.md
- Contribution guide: CONTRIBUTING.md
- Security reporting: SECURITY.md
