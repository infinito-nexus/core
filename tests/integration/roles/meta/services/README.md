# Role `meta/services.yml` Tests 🛎️

Integration tests that enforce invariants of each role's `meta/services.yml`: the dynamic-flag form (`"{{ '<role>' in group_names }}"`) MUST be used wherever a service entry depends on a sibling role's deployment, and a role's `services.yml` MUST NOT reference itself as a sibling provider.

Tests in this directory MUST only cover `meta/services.yml` shape and content. The ordering-only `galaxy_info.run_after` cluster lives in the [`run_after/`](run_after/) sub-cluster; coverage of `meta/variants.yml` lives one level up in [`../variants/`](../variants/); coverage of `meta/main.yml`'s `dependencies:` key lives in [`../dependencies/`](../dependencies/).

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../../docs/contributing/actions/testing/integration.md).
