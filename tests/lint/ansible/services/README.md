# Service Consistency Lints 🔗

Lint tests that enforce cross-file consistency between a role's `meta/services.yml` declarations and the rest of the role's configuration.

Tests in this directory MUST only cover service-graph consistency rules.

- `test_service_shared_consistency.py` enforces that every service whose `meta/services.yml` entry marks it `shared: true` exposes the required role-side bindings, and the inverse: a role consuming the shared form MUST declare the corresponding flag in its `meta/services.yml`.

For framework, directory layout, and `make test-lint` usage see [lint.md](../../../../docs/contributing/actions/testing/lint.md).
