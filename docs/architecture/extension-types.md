# Extension Types and Catalog Taxonomy

Extension types must remain distinct in the catalog because they differ in identity, execution, permissions, lifecycle, and operational risk. The Marketplace descriptions below are the examples supplied for this project's research; the labels are functional classifications, not independent audits of vendor behavior or security.

## Recommended catalog kinds

| Kind | Execution model | Typical responsibility | Default security posture |
| --- | --- | --- | --- |
| github-app | Installation identity plus webhooks/API | Persistent repository or organization integration | Per-installation, granular permissions; verify webhook signatures |
| hosted-service | Publisher-operated endpoint | Cross-system synchronization and dashboards | Narrow OAuth/App scopes; tenant isolation; egress and data review |
| github-action | Bounded workflow step | Lint, validate, test, package, scan | Pin immutable SHA; minimum job permissions; protect secrets |
| reusable-workflow | Versioned multi-job workflow | Shared CI/CD policy and orchestration | Review transitive actions; constrain secrets/environments |
| provider | Host-owned interface adapter | Swap vendor implementation without changing callers | Enforce caller policy and normalize errors/provenance |
| mcp-server | Typed external tools | AI/workflow-facing operations | Authorize each call server-side; approval for consequential writes |
| ui-extension | Navigation/views/commands | Inspect, compare, configure, navigate | Lazy-load; privileged work goes through authorized APIs |
| declarative | Data/config/rules only | Catalog entries, policy and UI metadata | No arbitrary execution or secrets |
| sandboxed-artifact | Isolated executable | Selected third-party workload | Deny-by-default network; quotas; immutable artifact identity |

## Examples from the supplied Marketplace snapshot

### Apps: mostly persistent hosted integrations

- CI/CD and delivery: Azure Pipelines, CircleCI.
- Image/repository maintenance: Imgbot.
- Backup and restore: Rewind Backups for GitHub.
- Code quality, coverage, static analysis, and configuration checks: Qlty Cloud, CodeFactor, Codecov, Codacy, DeepScan, Datree.
- Planning and issue/work synchronization: Zenhub, Zube, Atlassian.
- Test management: TestQuality.
- Engineering analytics: CodeScene, Waydev.
- Chat and notifications: Slack + GitHub, Octobox.

Architectural pattern: installation/configuration record + selected permissions + event intake + normalized data mapping + external result adapter. Hosted service operation is distinct from the GitHub UI surface.

### Actions: bounded workflow tasks

- Maintenance and release coordination: InfraNest Maintenance Window.
- Binary or schema compatibility: jardiff-bytecode-diff, Cambium GraphQL schema diff.
- Dependency, secret, and policy checks: PkgFire Dependency Firewall, Tripwire secret & dependency scan, DarkLens Compliance Scan, Datree-like configuration validation, cairnlock, composite-lint.
- Cache and artifact management: chromium-cache, BatchVault.
- Cost, SQL and deployment optimization: spendlint, SQLGuard, waveform plan, onprem-lb.
- Test integrity and repair: goalline, ai-fix for Maven.
- Accessibility and document compliance: PDF/UA Accessibility Check.
- Comment moderation: Unprofane Comment Moderation.
- Monitoring/alert control: stackalarm watch.
- Visualization/demonstration: bombgrid.

Architectural pattern: typed inputs/outputs + bounded process + job permissions + logs/artifacts + deterministic exit status. Multi-job orchestration belongs in reusable workflows rather than an overgrown single action.

## Catalog fields that should not be collapsed

Keep these as separate fields rather than one generic "plugin" status:

- Extension kind and runtime.
- Publisher identity and source repository.
- Version, immutable source revision/digest, and release provenance.
- Requested capabilities versus approved grants.
- Resource/tenant/environment scope.
- Credential references and expiry metadata (never the raw value).
- Trigger subscriptions and delivery guarantees.
- Data classes accessed and destinations receiving data.
- Compatibility range, license expression, dependency/SBOM summary.
- Review state, enablement state, health, last execution and last policy denial.

## Classification warning

A Marketplace listing is a discovery signal, not proof of safety, maintenance, license compatibility, performance, or suitability. Verify current source, permission requests, legal license, publisher, and release provenance before installation.
