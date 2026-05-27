# OAuth2 / OIDC Tests 🔐

Integration tests that enforce mutual-exclusivity between `oauth2`/`oidc` configurations across roles and validate that every OAuth2-proxy port is declared in `group_vars/all/09_ports.yml`.

Tests in this directory MUST only cover OAuth2 / OIDC configuration invariants. Generic port-uniqueness and port-reference-validity rules MUST live under `tests/integration/ports/`, and domain-related checks MUST live under `tests/integration/domains/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
