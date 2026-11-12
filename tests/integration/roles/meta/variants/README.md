# Role `meta/variants.yml` Tests 🔀

Integration tests that enforce invariants of each role's `meta/variants.yml`: the matrix-deploy variant list MUST exercise every dynamic flag declared in the role's `meta/services.yml` on both polarities, every service key referenced under `services:` in a variant MUST exist in `services.yml`, and the auth matrix (`oidc` / `oauth2` / `ldap`) MUST cover the LDAP-only branch.

Tests in this directory MUST only cover `meta/variants.yml` shape and coverage. Coverage of `meta/services.yml` itself lives in [`../services/`](../services/); coverage of `meta/main.yml`'s `dependencies:` key lives in [`../dependencies/`](../dependencies/).

## Memory budget exemptions

[test_resource_budget.py](test_resource_budget.py) caps every variant's deduplicated footprint at 32 GB `mem_reservation` and 64 GB `mem_limit`. A `# nocheck: mem-limit-budget` marker placed inside a variant's own entry in its role's `meta/variants.yml` waives the `mem_limit` cap for that one variant and never waives `mem_reservation`, which is the guarantee the host actually has to honour. The marker needs text after it; a bare one grants nothing.

The marker lives beside the pins that cause the overage, so it is visible to whoever edits them, and it is registered as a rule in [suppression.md](../../../../../docs/contributing/actions/testing/suppression.md) like every other suppression. It expires on its own: `test_every_mem_limit_exemption_is_still_needed` fails once the marked variant fits again, so it cannot outlive the cause it was written for. Add one only when no variant placement brings the footprint under the cap, and record in the text which placements were tried.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../../docs/contributing/actions/testing/integration.md).
