# Authorized Metadata Gateway

The gateway is a host-side reference boundary, not an identity provider. It consumes caller context, extension record, grant list and an audit sink supplied by the trusted host.

Before calling the read-only GitHub metadata provider, the gateway loads current extension and grant state from host-supplied loaders, constructs an exact tenant/principal/resource/capability/environment request, applies default-deny authorization, and appends an authorization event to the audit sink. If policy state or the pre-call audit append fails, the provider is not called.

The operation uses the capability repository.metadata.read and resource identifier github:repository:{owner}/{repo}, with owner and repository lowercased for GitHub's case-insensitive repository identity. The provider separately validates request path segments and the returned source identity.

Capability grants require a tenant identifier and match tenant, principal, extension version, capability, resource, and environment exactly. Cross-tenant grants are denied. The separate grant authority validates target and issuer tenant membership via host-supplied callbacks, checks issuer scope, requires an enabled extension version and a manifest-requested capability, validates expiry, and excludes revoked grants from its active set. High-impact capabilities also require an approval reference, but the reference is only an opaque pointer and is not authenticated by this code.

For each request, the gateway generates a correlation ID. Authorization denial/unavailability, authorized start, provider failure and successful completion events carry the same ID. Events include extension/version and manifest digest, principal, tenant, capability, resource, environment, outcome, decision/error code, timestamp, and source repository ID on success.

The SQLite store can serve directly as the operation audit sink. It persists events and correlation IDs across restarts. The gateway must use a trusted store instance and a host-owned identity/policy loader; durable audit rows do not authenticate the caller. The store fails closed before the outbound request if the authorization event cannot be written.

Integration tests demonstrate issuance → authorized read → revocation → denied subsequent read, plus extension disable → denied read with a grant still present. Tests use a fake transport, so they do not contact GitHub or perform external writes. This is evidence for reference behavior, not a production deployment test.

Production still requires authoritative caller identity, tenant membership and grant-scope services, authentic approval evidence, protected/tamper-evident audit storage, retention/backup controls, and operation-boundary authorization immediately before consequential side effects. This boundary authorizes only repository metadata reads, not repository contents or writes.
