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
| Combined validation | `make test` | Runs the main combined validation flow without the opt-in external suite. | Use this whenever a change touches at least one file that is not `.md` or `.rst`, or before opening a Pull Request. |

## Local Deploy and End-to-End Checks 🚀

For the retry-loop policy, use [Role Loop](../../agents/action/iteration/role.md) as the SPOT.
The table below is a command reference for the supported local deployment paths.

### Local Validation Commands 🏠

Use the following table when you need realistic local deployment validation or app-level end-to-end checks.

| Category | Command | What it does | When to use it |
|---|---|---|---|
| Local deploy | `make compose-deploy apps=web-app-nextcloud` | Creates the needed inventory and deploys one or more apps. | Fresh deploy for a specific app set. |
| Local deploy | `make compose-deploy mode=update apps=web-app-nextcloud` | Reuses an existing `devices.yml` inventory and redeploys one or more apps quickly. | Fast reuse path. |
| Local deploy | `make compose-deploy mode=update apps=web-app-nextcloud purge=true` | Reuses an existing `devices.yml` inventory, purges the entity first, and redeploys one or more apps quickly. | Fast reuse path after a state reset. |
| Local deploy and E2E | `make compose-deploy mode=reinstall apps=web-app-matomo` | Runs a dedicated local validation flow for one or more apps against the dev stack, cycling the stack and re-initializing the inventory first. | Baseline and recovery path. |
| Full local validation | `make compose-deploy` | Builds the broader local deployment flow across apps. | Broad coverage when you explicitly need it. |
| Bundle deploy | `make compose-deploy bundles="<bundle>[,<bundle>]"` | Aggregates the role groups from one or more [inventories/bundles/](../../../inventories/bundles/) entries into `apps` and runs the reinstall flow. Set `full_cycle=true` for the async update pass. | One-shot validation of a curated app shape (e.g. `education-suite`). |
| Bundle redeploy | `make compose-deploy mode=update bundles="<bundle>[,<bundle>]"` | Same bundle resolution as the bundle deploy, but routes through the reuse path (no down/up, no entity purge). | Fast iteration loop after a prior bundle deploy. |
| Local reset | `make compose-inventory-refresh` | Recreates the local inventory without deploying apps. | Use this when your local inventory is broken or you want a clean reset. |
| Local cleanup | `make compose-system-purge` | Deletes local deploy artifacts and cleanup data. | Use this only when you really want to remove local state. |

Important:

- Some local deploy commands are destructive.
- Read [reset/README.md](../../../scripts/tests/deploy/local/reset/README.md), [purge/README.md](../../../scripts/tests/deploy/local/purge/README.md), or [exec/README.md](../../../scripts/tests/deploy/local/exec/README.md) before using the matching helper.
- For act-based workflow checks, see [Act Workflow Checks](../tools/act.md).
- After a successful local deploy, run `make network-trust-ca` and restart your browser.

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
- [Playwright Tests](testing/playwright.md)
