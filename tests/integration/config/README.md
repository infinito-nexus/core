# Role Config Tests ⚙️

Integration tests that iterate `roles/*/config/main.yml` and enforce shape-level invariants: no `None` leaves, CSP structure, `services.<svc>.enabled` booleans.

Tests in this directory MUST only cover rules that apply uniformly across every role's `config/main.yml`. Per-role spot checks MUST live under [`spots/`](../spots/); configuration schema rules that validate `lookup('config', …)` paths MUST live under [`lookups/`](../lookups/).

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../docs/contributing/actions/testing/integration.md).
