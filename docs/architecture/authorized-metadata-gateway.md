# Authorized Metadata Gateway

The gateway is an in-memory reference boundary. It does not authenticate users, persist grants, or provide a production audit store.

Before calling the read-only GitHub metadata provider, the gateway loads current extension and grant state from trusted host-supplied loaders, constructs an exact tenant/principal/resource/capability/environment request, applies default-deny authorization, and appends an authorization event to the audit sink. If policy state or the pre-call audit append fails, the provider is not called.

The operation uses the capability `repository.metadata.read` and resource identifier `github:repository:{owner}/{repo}`, with owner and repository lowercased for GitHub's case-insensitive repository identity. The provider separately validates request path segments and the returned source identity.

Capability grants now require a tenant identifier and match tenant, principal, extension version, capability, resource, and environment exactly. Cross-tenant grants are denied.

For each allowed request, the gateway records both authorization and operation completion/failure events. Events include the extension key and manifest digest, principal, tenant, capability, resource, environment, outcome, decision/error code, timestamp, and source repository ID on success. The current in-memory sink is for tests only; production requires durable append-only audit storage.

The host must supply authenticated caller context and authoritative grant/record loaders. Grant issuance, revocation, tenant membership verification, token handling, and durable audit storage remain unimplemented. This boundary authorizes only repository metadata reads, not content reads or writes.
