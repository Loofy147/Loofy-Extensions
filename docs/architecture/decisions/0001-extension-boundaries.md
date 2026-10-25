# ADR 0001: Extension Contract and Trust Boundaries

- Status: Accepted as the initial design baseline
- Date: 2026-10-25
- Scope: Loofy-Extensions repository

## Context

The project starts from a repository with no implemented runtime. The target product needs to describe and eventually compose GitHub Apps, Actions, hosted integrations, provider adapters, MCP tools, UI extensions, declarative metadata, and selected isolated workloads. These types do not share identical execution or trust properties.

## Decision

1. Introduce a versioned JSON Schema contract at extensions.loofy/v1alpha1.
2. Use stable extension IDs and keep extension version, schema version, and host API version distinct.
3. Represent capabilities as provided and required declarations; represent requested permissions separately.
4. Treat schema validity as necessary but insufficient for approval or execution.
5. Keep credentials outside manifests and reference secrets through a vault locator only.
6. Default network access to deny. Declare explicit host allowlists when a runtime needs network.
7. Keep persistent hosted integrations distinct from bounded GitHub Actions tasks.
8. Start with metadata validation and a read-only provider plus deterministic validation task.
9. Defer arbitrary third-party execution until sandboxing, provenance, lifecycle revocation, and audit behavior have tests.
10. Use a feature branch and pull request as the default repository change path.

## Consequences

Positive:
- Reviewers can inspect requested capabilities before code executes.
- Extension types can evolve without collapsing into a universal plugin abstraction.
- The initial implementation is testable without credentials, a database, or deployment.
- Future runtime decisions can be made from tested contracts.

Trade-offs:
- More metadata is required for each extension.
- The first schema is intentionally a project-specific v1alpha1 contract, not an external standard.
- A schema does not enforce runtime permissions; policy enforcement remains future work.

## Rejected alternatives

- A single generic plugin field with unrestricted runtime behavior: rejected because permissions and lifecycle differ by type.
- Immediate public marketplace or arbitrary code loader: rejected because trust and operational controls are not implemented.
- Premature microservice split: deferred until service boundaries and scaling needs are demonstrated.
