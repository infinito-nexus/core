# Identity & Access Integration Tests 🔐

Integration tests for identity and access surfaces: OAuth2 / OIDC configuration invariants (mutual exclusion, ACL shape, proxy port allocation, RBAC group-path declarations) and password / secret quoting rules.

Each child directory pins one IAM surface; see the per-directory README for scope. Generic OIDC-redirect URI checks and domain rules live under [`meta/domains/`](../meta/domains/); port allocations live under `tests/integration/ports/` once introduced.

For framework and `make test-integration` usage see [integration.md](../../../docs/contributing/actions/testing/integration.md).
