# Playwright Spec Loop

This page defines the inner loop for iterating on a role-local `files/playwright/playwright.spec.js` against an already-running app stack, without redeploying between edits.

## Definitions

- **Inner loop**: the edit-rerun cycle on `roles/<role>/files/playwright/playwright.spec.js` driven by `make compose-playwright role=<role>`, without a redeploy.
- **Staging dir**: `TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR/<role>` (default `/tmp/test-e2e-playwright/<role>`). Contains the rendered `.env` and the Playwright project from the last deploy.
- **Baseline deploy**: a successful `make compose-deploy mode=reinstall apps=<role> full_cycle=true` run as defined in [Role Loop](role.md).
- **Pass**: `make compose-playwright role=<role>` exits `0` AND every MUST in [Contributing `playwright.spec.js`](../../../contributing/artefact/files/role/playwright.specs.js.md) holds for the resulting run.

## Preconditions

You MUST NOT enter the inner loop unless all of the following hold:

1. A baseline deploy for `<role>` completed successfully in the current environment.
2. The app stack for `<role>` is still running.
3. The staging dir exists and contains a non-empty `.env`.
4. `roles/<role>/files/playwright/playwright.spec.js` exists.

If any precondition fails, you MUST return to [Role Loop](role.md) and re-establish the baseline before continuing.

## Required reading

You MUST load the following pages before editing any file, in this order:

1. [Contributing `playwright.spec.js`](../../../contributing/artefact/files/role/playwright.specs.js.md): authoritative MUSTs for the spec content. Every MUST there is an acceptance criterion for this loop.
2. [Agent `playwright.spec.js` procedure](../../files/role/playwright.spec.js.md): how to generate or update the spec.
3. [Agent `playwright.env.j2` procedure](../../files/role/playwright.env.j2.md): rendered test input contract; required whenever the spec reads a new variable.
4. [Playwright Tests](../../../contributing/actions/testing/playwright.md): framework SPOT for runner, image pin, and recording tools.
5. [Role Loop](role.md): baseline deploy, Certificate Authority trust, Inspect-before-redeploy.

## Procedure

1. Verify every item in [Preconditions](#preconditions). If any fails, exit this page and follow [Role Loop](role.md).
2. Edit `roles/<role>/files/playwright/playwright.spec.js`. You MUST NOT hand-edit the staged copy under `TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR/<role>/tests/`; the rerunner overwrites it from the repo on each run.
3. Run `make compose-playwright role=<role> keep=true`. You MAY pass `pw="--grep <pattern>"` (or any other `npx playwright test` argument). Set `keep=true` on every inner-loop run regardless of the previous result; omit only when the user has explicitly opted out. For the full propagation chain see [Playwright Tests](../../../contributing/actions/testing/playwright.md#artefact-retention-).
4. Inspect the run output before deciding pass / fail; a green Playwright exit only proves no `expect(...)` threw, not that the contract is satisfied:
   - You MUST read the per-test logs for every run: the `list` reporter output, `playwright-report/index.html`, and `test-results/<test>/error-context.md` for any failed test.
   - You MUST verify schema conformance per [Contributing `playwright.spec.js`](../../../contributing/artefact/files/role/playwright.specs.js.md): persona names match `<persona>: <flow>`, every skip routes through `PERSONA_<X>_BLOCKED=true` or `<NAME>_SERVICE_ENABLED=false` (never runtime detection), and every persona reaches an authenticated surface and drives a role-specific interaction.
   - With `INFINITO_PLAYWRIGHT_KEEP=true` you MUST open the trace / video of at least one passing persona per run, to confirm the journey actually fired.
5. If the script exits `0` AND the inspection passed, go to [Exit](#exit).
6. If the script exits non-zero OR the inspection surfaced a schema violation:
   1. If the failure needs a change **outside** `files/playwright/playwright.spec.js` (role tasks, templates, vars, config, `javascript.js`, `style.css`, or any other role asset the deploy materializes), go to [Escape](#escape).
   2. Otherwise, adjust the spec and return to step 2.

## Debugging in the nested docker daemon

To validate a hypothesis without redeploying — e.g. rerun the Playwright image with a patched env or grep — use `make compose-inner-run` (see `make help target=compose-inner-run` for `IMAGE` / `cmd` / `INFINITO_RUN_FLAGS`). You MAY hand-edit `/tmp/test-e2e-playwright/<role>/.env` for the diagnosis run only, but you MUST mirror any fix back into `roles/<role>/templates/playwright.env.j2` before the next deploy.

## Exit

You MUST NOT report the task complete until all of the following hold:

1. `make compose-playwright role=<role>` has exited `0` on the current spec.
2. Every MUST in [Contributing `playwright.spec.js`](../../../contributing/artefact/files/role/playwright.specs.js.md) holds, including the live-application assertion and the logged-out final state.
3. A final `make compose-deploy mode=reinstall apps=<role> full_cycle=true` run has completed with the spec passing against the freshly provisioned stack. Inner-loop passes alone do NOT satisfy this gate.

## Escape

When the failure requires a change outside `files/playwright/playwright.spec.js`:

1. You MUST stop the inner loop. Inner-loop runs do NOT pick up role changes.
2. You SHOULD run `make compose-deploy mode=update apps=<role>` for the redeploy.
3. You MUST NOT fall back to `make compose-deploy mode=reinstall apps=<role> full_cycle=true` unless the reuse path has concrete evidence of a broken inventory or host stack, per [Role Loop](role.md).
4. After the redeploy succeeds, return to [Procedure](#procedure) step 1.
