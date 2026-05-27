# Role `meta/main.yml` Tests 🧾

Integration tests that enforce invariants of each role's `meta/main.yml`: the file MUST exist for every role under `roles/`, and `galaxy_info` MUST carry the fields the Sphinx generator expects (non-empty `description`, no `None` values).

Tests in this directory MUST only cover `meta/main.yml` presence and field shape. Tests about role dependencies declared in that file (`dependencies:`) MUST live under [`dependencies/`](dependencies/); checks tied to `meta/services.yml` MUST live under [`services/`](services/) (with the ordering-only `galaxy_info.run_after` checks under [`services/run_after/`](services/run_after/)); checks against `meta/variants.yml` MUST live under [`variants/`](variants/).

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
