# Testing and Validation ✅

Use the real commands from the repository. Run them from the repository root.

This repository uses several test and validation types:

- `Lint and syntax checks` catch style, formatting, and Ansible syntax problems early.
- `Unit tests` verify isolated logic.
- `Integration tests` verify behavior across modules and runtime boundaries.
- `External tests` verify live third-party state such as public registries or services when hermetic checks are insufficient.
- `Combined validation` runs the standard main verification flow.
- `Local deploy and E2E validation` checks whether apps and deployment flows work in a realistic local stack.

## Code Quality and Automated Checks 🔎

Use the following table to choose the right lint, syntax, unit, integration, or combined validation command for your change.

### Validation Commands 🛠️

| Category | Command | What it does | When to use it |
|---|---|---|---|
| Lint | `make lint` | Runs the main lint checks for the repository. | Use this when you want a broad lint pass before pushing. |
| Syntax | `make lint-ansible` | Runs the Ansible syntax validation for `playbook.yml`. | Use this when you changed Ansible roles, inventories, or playbook-related files. |
| Lint tests | `make test-lint` | Runs the lint test suite inside the development environment. | Use this when you want CI-like lint validation. |
| Unit tests | `make test-unit` | Runs the unit test suite. | Use this when you changed Python logic or other isolated code paths. |
| Integration tests | `make test-integration` | Runs the integration test suite. | Use this when your change affects behavior across modules or runtime boundaries. |
| External tests | `make test-external` | Runs opt-in tests that depend on live third-party systems such as public registries. | Use this when you need live external verification. It is intentionally excluded from `make test`. |
| Security tests | `make test-security` | Builds a Syft SBOM of every pinned role image from the GHCR mirror and scans it with Trivy, Grype and OSV at the threshold of `sys-ctl-hlth-runtime`. | Use this when you bump or add an image pin. It is excluded from `make test` and runs daily in `cron-images-mirror-all.yml`. |
| Combined validation | `make test` | Runs the main combined validation flow without the opt-in external suite. | Use this whenever a change touches at least one file that is not `.md` or `.rst`, or before opening a Pull Request. |

## Local Deploy and End-to-End Checks 🚀

For the retry-loop policy, use [Compose Loop](../../../agents/skills/i8-iterate-compose/SKILL.md) as the SPOT.
The table below is a command reference for the supported local deployment paths.

### Local Validation Commands 🏠

Use the following table when you need realistic local deployment validation or app-level end-to-end checks.

| Category | Command | What it does | When to use it |
|---|---|---|---|
| Local deploy | `make compose-deploy apps=web-app-nextcloud` | Creates the needed inventory and deploys one or more apps. | Fresh deploy for a specific app set. |
| Local deploy | `make compose-deploy mode=update apps=web-app-nextcloud` | Reuses an existing `devices.yml` inventory and redeploys one or more apps quickly. | Fast reuse path for a change outside the inventory-baked meta files (`meta/services.yml`, `meta/variants.yml`, `meta/secrets.yml`, `meta/users.yml`). |
| Local deploy | `make compose-deploy mode=update apps=web-app-nextcloud purge=true` | Reuses an existing `devices.yml` inventory, purges the entity first, and redeploys one or more apps quickly. | Fast reuse path after a state reset. |
| Local deploy and E2E | `make compose-deploy mode=reinstall apps=web-app-matomo` | Runs a dedicated local validation flow for one or more apps against the dev stack, cycling the stack and re-initializing the inventory first. | Baseline and recovery path, and the redeploy after a change to an inventory-baked meta file. |
| Full local validation | `make compose-deploy` | Builds the broader local deployment flow across apps. | Broad coverage when you explicitly need it. |
| Bundle deploy | `make compose-deploy bundles="<bundle>[,<bundle>]"` | Aggregates the role groups from one or more [inventories/bundles/](../../../inventories/bundles/) entries into `apps` and runs the reinstall flow. Set `full_cycle=true` for the update pass. | One-shot validation of a curated app shape (e.g. `education-suite`). |
| Bundle redeploy | `make compose-deploy mode=update bundles="<bundle>[,<bundle>]"` | Same bundle resolution as the bundle deploy, but routes through the reuse path (no down/up, no entity purge). | Fast iteration loop after a prior bundle deploy. |
| Local reset | `make compose-inventory-refresh` | Recreates the local inventory without deploying apps. | Use this when your local inventory is broken or you want a clean reset. |
| Local cleanup | `make compose-system-purge` | Deletes local deploy artifacts and cleanup data. | Use this only when you really want to remove local state. |

Important:

- Some local deploy commands are destructive.
- Read [reset/README.md](../../../scripts/tests/deploy/local/reset/README.md), [purge/README.md](../../../scripts/tests/deploy/local/purge/README.md), or [exec/README.md](../../../scripts/tests/deploy/local/exec/README.md) before using the matching helper.
- For act-based workflow checks, see [Act Workflow Checks](../tools/act.md).
- After a successful local deploy, run `make network-trust-ca` and restart your browser.

## Iteration Plan 🧭

`make iterate-plan [base=<ref>] [loop=auto]` prints what an iteration on a diff has to run and names every cut: each role, mode or test it leaves out, with the reason. See the [Makefile](../../../Makefile) for every parameter. Each changed path is classified: a role path seeds its role, a format-only edit reaches nothing, a changed lint directive runs the lint suite, a shared plugin, module, script or `group_vars` key reaches whatever consumes it, and an unknown path widens to every role. An edit is format-only when the Python tree, or the YAML or JSON data with every value's type, stays the same and neither side carries a comment a deploy or a deployed program reads: a `# variant-pin:` comment, a `# nocheck:` rule whose reader is not a lint (`inventory-open-subtree`, `inventory-variable`, `header-trust`, `license-declared`), a Python coding cookie or Ansible's `WANT_JSON` marker. YAML and JSON a role ships under `files/` or `templates/` must keep an identical text. A role path also runs the unit tests that name the role. A module or script that a Makefile target outside deploys (lint, test, `iterate-plan` and the like) runs lists that target in T0; one that any other target runs widens to every role, and so does an edit of the Makefile itself.

| Tier | Holds | When to run it |
|---|---|---|
| T0 | The unit tests and lint commands of the changed files, plus the tooling make targets that run them, listed to pick from since one may be interactive. | After every edit. |
| T1 | One inner-loop row per changed path that seeds roles: the cheapest row across that path's roles in the chosen loop, such as `make compose-role-sync`, `make compose-deploy mode=update` or `make swarm-zombie`. Identical rows merge; the full set takes its cheapest base-cluster row. | While iterating. |
| T2 | The pre-push rows (the compose gate and one `make swarm-zombie` per swarm variant, or `make roundtrip` for the full set) and `make test`. | Before a push. |
| T3 | The CI whitelist of the diff. | In CI. |

- `cuts` names, with the reason, every role a tier leaves out, the test suites T0 leaves to `make test`, and every changed path other than a document or a format-only edit that nothing in the plan exercises. A role that `scripts/meta/resolve/diff/affected_roles.sh` deploys for the same diff but the plan narrows away sits in a cut of tier `all`, with the paths that allowed it.
- That baseline is narrower than the truth. Its closure follows `run_after`, dependency and service edges, so a cross-role Jinja include is covered only where such an edge matches, and a renamed role path seeds only the new role. The plan lists changed paths with rename detection off, so a move counts both its old and its new path.
- Every row carries a footprint (the declared `min_storage` against the free space and its floor) and a cost. The output names the cost source: the declared storage, or the measured seconds of the deploy log or role-runtimes CSV passed as `timings=`.
- `format=json` prints the machine-readable plan with the keys `base`, `head`, `loop`, `mode`, `variant`, `network`, `disable`, `kept`, `full`, `seeds`, `roles`, `baseline`, `changed`, `tiers`, `rows`, `footprint`, `cost`, `cuts` and `elapsed_s`.
- The plan fetches nothing and reads the refs as they are. The symbol index and the resolver read the current tree.

## Suite Selection 🎯

- When exactly one test file changes inside one test family, you MAY scope the run with `INFINITO_TEST_PATTERN`.
- When two or more test files change inside the same test family, you MUST run the matching suite command without `INFINITO_TEST_PATTERN`:
  `make test-lint`, `make test-unit`, `make test-integration`, or `make test-external`.
- When a change touches multiple test families, you MUST run every affected suite.

## Testing Standards 📋

For test-type-specific requirements, framework, and creation procedures see:

- [Unit Tests](testing/unit.md)
- [Integration Tests](testing/integration.md)
- [External Tests](testing/external.md)
- [Upstream References](testing/upstream.md)
- [Playwright Tests](testing/playwright.md)
