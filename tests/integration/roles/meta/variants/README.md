# Role `meta/variants.yml` Tests 🔀

Integration tests that enforce invariants of each role's `meta/variants.yml`: the matrix-deploy variant list MUST exercise every dynamic flag declared in the role's `meta/services.yml` on both polarities, every service key referenced under `services:` in a variant MUST exist in `services.yml`, and the auth matrix (`oidc` / `oauth2` / `ldap`) MUST cover the LDAP-only branch.

Tests in this directory MUST only cover `meta/variants.yml` shape and coverage. Coverage of `meta/services.yml` itself lives in [`../services/`](../services/); coverage of `meta/main.yml`'s `dependencies:` key lives in [`../dependencies/`](../dependencies/).

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../../docs/contributing/actions/testing/integration.md).
