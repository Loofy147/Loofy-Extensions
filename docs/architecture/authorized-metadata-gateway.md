# Authorized Metadata Gateway

The gateway is an in-memory reference boundary. It does not authenticate users, persist grants, or provide a production audit store.

Before calling the read-only GitHub metadata provider, the gateway loads current extension and grant state from trusted host-supplied loaders, constructs an exact tenant/principal/resource/capability/environment request, applies default-deny authorization, and appends an authorization event to the audit sink. If policy state or the pre-call audit append fails, the provider is not called.

The operation uses the capability `repository.metadata.read` and resource identifier `github:repository:{owner}/{repo}`, with owner and repository lowercased for GitHub's case-insensitive repository identity. The provider separately validates request path segments and the returned source identity.

Capability grants require a tenant identifier and match tenant, principal, extension version, capability, resource, and environment exactly. Cross-tenant grants are denied. The separate in-memory grant authority validates target and issuer tenant membership via host-supplied callbacks, checks issuer scope, requires an enabled extension version and a manifest-requested capability, validates expiry, and excludes revoked grants from its active set. High-impact capabilities also require an approval reference, but the reference is only an opaque pointer and is not authenticated by this code.

For each allowed request, the gateway records both authorization and operation completion/failure events. Events include the extension key and manifest digest, principal, tenant, capability, resource, environment, outcome, decision/error code, timestamp, and source repository ID on success. The current in-memory sink is for tests only; production requires durable append-only audit storage. Grant issuance/revocation events are likewise stored only in memory.

Integration tests demonstrate issuance → authorized read → revocation → denied subsequent read, plus extension disable → denied read with a grant still present. All use a fake transport, so they do not contact GitHub or perform external writes. This is evidence for reference behavior, not a production deployment test.

The host must supply authenticated caller context, authoritative and current record/grant loaders, tenant membership verification, and grant-scope authority. Production still requires durable transactional grant/revocation/audit storage, authentic approval evidence, and operation-boundary authorization immediately before consequential side effects. This boundary authorizes only repository metadata reads, not repository contents or writes.
