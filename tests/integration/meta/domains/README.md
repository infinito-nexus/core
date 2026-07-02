# Domain Tests 🌐

Integration tests that enforce the shape and uniqueness of `domains.{canonical,aliases}` across all roles and validate that `get_domain()` references point to real `application_id`s.

Tests in this directory MUST only cover domain declarations (structure, uniqueness, reference validity). Tests related to port registration, OIDC redirect URIs, or CSP handling MUST live elsewhere under `tests/integration/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
