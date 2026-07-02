# Playwright Tests 🎭

This page covers Playwright end-to-end test requirements, runner integration, and file contracts.
For implementation guidance when writing or updating role-local files, see
[Agent `playwright.spec.js`](../../../agents/files/role/playwright.spec.js.md) and
[Agent `playwright.env.j2`](../../../agents/files/role/playwright.env.j2.md).
For what the `files/playwright/playwright.spec.js` of a role MUST contain, see
[`playwright.spec.js` (role file rules)](../../artefact/files/role/playwright.specs.js.md).

## Framework 🧰

- [Playwright](https://playwright.dev/) runs inside Docker via the shared `test-e2e-playwright` role.
- There is no standalone `make` target for Playwright. Tests run as part of local deploy flows
  (e.g. `make compose-deploy mode=reinstall apps=web-app-matomo full_cycle=true`). For spec-only
  iteration after the first successful deploy, see [Playwright Spec Loop](../../../agents/action/iteration/playwright.md).

## When to Write ✍️

- You MUST provide Playwright tests for every `web-*` role.
- For when a spec MUST be added or updated (including the `javascript.js` / `style.css` trigger), see the Scenarios section of [`playwright.spec.js`](../../artefact/files/role/playwright.specs.js.md#scenarios-).

## Role-Local Files 📁

Every Playwright-enabled role MUST provide exactly these two files:

| File | Purpose |
|---|---|
| `files/playwright/playwright.spec.js` | Test scenarios executed by the Playwright runner |
| `templates/playwright.env.j2` | Rendered `.env` passed to the Playwright container |

`playwright.config.js` MUST remain centralized in `roles/test-e2e-playwright/files/` and `package.json` in `roles/test-e2e-playwright/templates/package.json.j2` (rendered per-deploy into the staging dir). You MUST NOT duplicate or override either per role.

The `@playwright/test` version pinned into the rendered `package.json` comes from `playwright.version` in `roles/test-e2e-playwright/meta/services.yml` via the `image_version` filter. That YAML value is the single source of truth for the Playwright version.

## CI Image Source 🪞

The Playwright container image is declared in `roles/test-e2e-playwright/meta/services.yml` under the `playwright` service entry (`image:` + `version:`). CI mirrors that image into GHCR through the standard mirror pipeline before deploy tests run, so Playwright jobs do not depend on direct pulls from MCR during the test phase.

The `version:` MUST stay pinned to an exact Playwright version and distro pair such as `v1.59.1-noble`. You MUST NOT switch this to a mutable tag such as `latest`, because mutable upstream tags are more vulnerable to CDN propagation delays and make flaky CI failures much harder to reason about.

## Runner 🚀

The `test-e2e-playwright` role discovers Playwright-enabled roles through the presence of
`templates/playwright.env.j2`. For each discovered role it:

1. stages the test project
2. renders `.env` from `playwright.env.j2`
3. copies `files/playwright/playwright.spec.js` into the project as `tests/playwright.spec.js`
4. renders the central `templates/package.json.j2` and copies the central `files/playwright.config.js` into the staging dir
5. waits until the app is reachable
6. runs Playwright in Docker

## Artefact Retention 🎞️

The runner keeps Playwright traces, screenshots, and videos for every test only when the resolved environment variable `INFINITO_PLAYWRIGHT_KEEP` evaluates to `true` (case-insensitive).
Any other value, including unset or empty, keeps artefacts only when a test fails.

The propagation chain has four hops:

1. The host environment variable `INFINITO_PLAYWRIGHT_KEEP` (set on the host shell, by `act --env INFINITO_PLAYWRIGHT_KEEP=true`, or by the GitHub Actions repository variable forwarded into each `test-deploy-*.yml` workflow as `INFINITO_PLAYWRIGHT_KEEP: ${{ vars.INFINITO_PLAYWRIGHT_KEEP }}`).
2. `roles/test-e2e-playwright/defaults/main.yml` reads the host value into `test_e2e_playwright_keep` via `lookup('env', 'INFINITO_PLAYWRIGHT_KEEP')`. Inventory MAY override the role variable per environment in `group_vars` or `host_vars`.
3. `roles/test-e2e-playwright/tasks/02_run_one.yml` forwards the resolved value into the Playwright container as `-e INFINITO_PLAYWRIGHT_KEEP={{ test_e2e_playwright_keep }}`.
4. `roles/test-e2e-playwright/files/playwright.config.js` switches `trace`, `screenshot`, and `video` to `on` when the container value is `true`. It otherwise leaves the failure-only defaults (`retain-on-failure` for trace and video, `only-on-failure` for screenshot).

Set the variable for the contexts you need:

- **Local deploy**: prefix every `make compose-deploy` invocation with `INFINITO_PLAYWRIGHT_KEEP=true`.
- **Local `act` runs**: append `--env INFINITO_PLAYWRIGHT_KEEP=true` to the `act` command.
- **CI**: set the `INFINITO_PLAYWRIGHT_KEEP` repository variable. For the GitHub click path see [CI Configuration](../../tools/github/actions/configuration.md#infinito_playwright_keep-).
- **Inventory pin**: set `test_e2e_playwright_keep: "true"` in `group_vars` or `host_vars` of the target environment.

| Resolved container value | Trace | Screenshot | Video |
|---|---|---|---|
| `true` (case-insensitive) | `on` | `on` | `on` |
| any other value, unset, or empty | `retain-on-failure` | `only-on-failure` | `retain-on-failure` |

## File Requirements 📄

See the dedicated SPOT pages for authoring rules:

- [`playwright.spec.js`](../../artefact/files/role/playwright.specs.js.md): what the role-local spec MUST contain (entry point, scenarios, selectors, final state)
- [`playwright.env.j2`](../../../agents/files/role/playwright.env.j2.md): rendered test input surface, variable naming, and entry-point selection

## Recording Tests 🎬

### Playwright Codegen (built-in) 🔧

Playwright ships a built-in code recorder:

```bash
npx playwright codegen https://<app-url>
```

This opens the Playwright Inspector alongside a browser. Every interaction is recorded and emitted as a runnable spec. Use the output as a starting draft and clean it up according to the authoring rules in [`playwright.spec.js`](../../artefact/files/role/playwright.specs.js.md).

### playwright-recorder (Docker-based) 🐳

For infrastructure-heavy setups where Playwright should not live in the main repository, use [playwright-recorder](https://github.com/kevinveenbirkenbach/playwright-recorder). It wraps Playwright codegen in Docker with X11/XWayland forwarding and an ephemeral workspace so no state leaks between recordings.

Requirements: Docker, X11 or XWayland, `xhost`

```bash
# Install
make install

# Record a flow starting at a specific URL
make codegen
# or directly:
./scripts/codegen.sh https://<app-url>/login

# Replay a recorded spec headlessly
make replay
# or directly:
./scripts/replay.sh recordings/login.spec.ts
```

Generated files are persisted in the local workspace (git-ignored). Copy the relevant parts into `files/playwright/playwright.spec.js` and adapt them.

## Development Procedure 📋

This page owns framework and runner mechanics only. The procedure for writing, deploying, and reviewing a role-local spec lives in the dedicated SPOTs:

- [Agent `playwright.spec.js`](../../../agents/files/role/playwright.spec.js.md): authoring procedure and live review.
- [Compose Loop](../../../agents/action/iteration/compose.md): baseline deploy, redeploy rules, Certificate Authority trust, Inspect-before-redeploy.
- [Playwright Spec Loop](../../../agents/action/iteration/playwright.md): spec-only inner loop against the already-running stack.
- [`playwright.spec.js` (role file rules)](../../artefact/files/role/playwright.specs.js.md): what the spec MUST contain, including logged-out final state and console cleanliness.
