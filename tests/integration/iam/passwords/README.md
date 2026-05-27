# Password Handling Tests 🔑

Integration tests that enforce safe handling of secrets across roles: env-file values MUST be quoted, shell tasks MUST quote password expansions, and password *definitions* MUST NOT apply the `quote` filter (which corrupts the stored value).

Tests in this directory MUST only cover password/secret quoting and definition rules. Tests for filter plugins, Jinja syntax, or compose structure MUST live elsewhere under `tests/integration/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
