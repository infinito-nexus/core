# Role Loop

Use this page for iterating on a local app deploy during role-level debugging or development.
For spec-level inner-loop iteration, see [Playwright Spec Loop](playwright.md).
For workflow-level iteration with Act, see [Workflow Loop](workflow.md).

## Rules

- Before starting the loop, you MUST propose disabling all non-necessary services via the `disable=` make arg to reduce resource usage. In the typical case, this means keeping only the database and disabling everything else. Only proceed without this proposal if the user has already confirmed a full-stack setup.
- Non-essential provider toggle:
  - WHEN: before first deploy of iteration.
  - ACTION: ask user "disable matomo, dashboard, prometheus, email, css providers? [Y/n]".
  - DEFAULT: yes (disable all five).
  - SKIP ASK: only if user already answered explicitly in this iteration.
  - ON YES: pass `disable="matomo,dashboard,prometheus,email,css"` verbatim to every deploy command. The value is a comma-separated list of provider keys, NOT a glob, NOT a `web-app-*.services.*` path.
  - ON NO: omit the arg entirely.
  - SIDE EFFECT (yes): inventory initializer auto-removes the provider roles `web-app-matomo`, `web-app-dashboard`, `web-app-prometheus`, `web-app-mailu`, and `web-svc-css`. Do NOT list them in `apps=`.
  - PERSIST: record answer at top of iteration. Reuse for all subsequent deploys without re-asking.
- You MUST run `make test` before every deploy. Only proceed with the deploy if all tests pass.
- You MUST prepend `INFINITO_PLAYWRIGHT_KEEP=true` to every `make compose-deploy` command in the iteration (any mode), so trace, screenshot, and video of passing Playwright tests stay inspectable. Omit only when the user has explicitly opted out of per-test artefacts. For the full propagation chain see [Playwright Tests](../../../contributing/actions/testing/playwright.md#artefact-retention-).
- Unless the user explicitly says to reuse the existing setup, you MUST start once with `make compose-deploy mode=reinstall apps=<roles> full_cycle=true` to establish the baseline inventory and clean app state. `full_cycle=true` adds the async update pass (pass 2) and MUST stay on unless the user explicitly asks to skip it.
- You MUST NOT run more than one deploy command at the same time. Deployments MUST be executed serially, never in parallel.
- To speed up debugging, you MAY pass multiple apps at once, e.g. `make compose-deploy mode=reinstall apps="<roles> <roles>" full_cycle=true`.
- After that, you MUST use `make compose-deploy mode=update apps=<roles>` for the default edit-fix-redeploy loop.
- Do NOT rerun `make compose-deploy mode=reinstall apps=<roles> full_cycle=true` just because a deploy failed or you changed code. That restarts the stack unnecessarily and burns time.
- If the same failure still reproduces on the reuse path and you want to test whether app entity state is involved, use `make compose-deploy mode=update apps=<roles> purge=true` once.
- After that targeted purge check, you MUST return to `make compose-deploy mode=update apps=<roles>`.
- Only go back to `make compose-deploy mode=reinstall apps=<roles> full_cycle=true` if you have concrete evidence that the inventory or host stack is broken, or you intentionally need a fresh single-app baseline again.
- Network or DNS failures during a local deploy count as concrete evidence that the host stack is broken. In that case, the next retry MUST be `make compose-deploy mode=reinstall apps=<roles> full_cycle=true`.
- If you need to validate the single-app init/deploy path separately, use `make compose-deploy apps=<roles>`.

## Matrix variants

For the matrix-variant mechanism (folder layout, round semantics, `--variant` / `--full-cycle` flags) see [variants.md](../../../contributing/design/variants.md). The agent-side iteration rules below assume that mechanism as background.

- Before you start a Role Loop on a matrix-variant role, you MUST decide if the iteration targets the FULL matrix (validates every variant) or ONE specific variant (focused debug). State the choice explicitly before the first deploy.
- For focused debug on variant `<idx>`, you MUST pin `variant=<idx>` on every command in the iteration. Mixing pinned and unpinned commands silently retargets a different folder.
- Default focused-debug recipe: `make compose-deploy mode=reinstall apps=<role> full_cycle=true variant=<idx>` once for the variant baseline, then `make compose-deploy mode=update apps=<role> variant=<idx>` for the edit-fix-redeploy loop.
- First contact with a previously-untouched `variant=<idx>` MUST be `make compose-deploy mode=reinstall apps=<roles> variant=<idx>`, never a reuse target. Reuse re-pins the live stack onto stale volumes, DB rows and network aliases from the previously-pinned variant, producing split-brain app state.
- If a reuse target aborts with "inventory not found", you MUST add `variant=<idx>` and re-run; do NOT work around the error by re-creating the unsuffixed folder by hand.
- For FULL-matrix iteration, omit `variant=`. If any round fails, capture WHICH round was the last successful one so the next redeploy can pin `variant=<that-idx>` to it.
- When debugging cross-variant interaction (for example "the multisite variant breaks because single-site state was not purged"), reproduce with the FULL matrix once, then pin `variant=<failing-idx>` and iterate the fix. Re-run the FULL matrix only when you believe the fix is complete.

### Full-matrix iteration flow

When the iteration target is the full matrix (cross-variant coverage matters more than focused-debug speed), apply the following recipe instead of cycling all variants on every loop:

1. **Iterate the failing variant with `mode=update`, variant-pinned.** `mode=update` MUST always carry `variant=<idx>`. Never use `mode=update` to cycle the full matrix. Loop `make compose-deploy mode=update apps=<roles> variant=<idx>` until that variant is green.
2. **Deploy each remaining variant that has NOT yet been re-deployed against the current code** with `make compose-deploy mode=reinstall apps=<roles> full_cycle=true variant=<other-idx>`. This avoids re-doing the fixed variant while validating the others against the current code as a fresh baseline.
3. **Finally, re-run the FULL matrix one more time** with `make compose-deploy mode=reinstall apps=<roles> full_cycle=true` (no `variant=`). This is the canonical end-of-iteration gate — every variant against the current code, fresh state.

## Certificate Authority

- If the website uses locally deployed certificates, you MUST run `make network-trust-ca` before you inspect it in a browser. Otherwise the browser will warn about the local CA and the inspection will not be reliable.
- After `make network-trust-ca`, you MUST restart the browser so it picks up the updated trust store.
- If `make network-trust-ca` fails due to missing root permissions, you MUST use the alternative syntax `curl -k` (or `wget --no-check-certificate`) to skip certificate validation when checking URLs from the command line instead of fixing the trust store.

## Inspect

- Before you redeploy, you MUST complete all available inspections first. Check the live local output, local logs, and current browser state so the original state stays visible.
- To inspect files or run commands inside a running container, use `make compose-exec`.
- To run a one-off sidecar image against the same docker daemon (e.g. a Playwright runner with a patched `.env`), use `make compose-inner-run` (see `make help target=compose-inner-run` for `IMAGE` / `cmd` / `INFINITO_RUN_FLAGS`).
- When a local deploy fails, you MUST validate the proposed fix inside a sidecar against the same image via `make compose-inner-run` (or `make compose-exec` against the live container) BEFORE starting another deploy, whenever the failure is reproducible there. The reproducible-there set includes: a container that crashes at startup, a misconfigured env var, an image-side bug, an in-container script that fails, or any failure whose root cause was traced to runtime state of the container. The only exception is failures that genuinely depend on multi-container or post-deploy state (network neighbours, persistent volumes, post-deploy Ansible hooks) — call that out explicitly in the iteration narrative.
- When the failure is in a Playwright spec, "in-container validation" specifically means running `make compose-playwright role=<role>` against the live stack (per [Playwright Spec Loop](playwright.md)).
- Use the same live investigation to identify the concrete root cause and save iteration time.
- Once the root cause is understood, you MUST apply the real fix in the repository files and then continue the redeploy loop with the usual commands from this page. In-container fixes are only for diagnosis or short validation and MUST NOT replace the repo change.
