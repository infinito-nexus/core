# Role Loop

Use this page for iterating on a local app deploy during role-level debugging or development.
For spec-level inner-loop iteration, see [Playwright Spec Loop](playwright.md).
For workflow-level iteration with Act, see [Workflow Loop](workflow.md).

## Rules

- Before starting the loop, you MUST propose disabling all non-necessary services via `SERVICES_DISABLED` to reduce resource usage. In the typical case, this means keeping only the database and disabling everything else. Only proceed without this proposal if the user has already confirmed a full-stack setup.
- Matomo+email provider toggle:
  - WHEN: before first deploy of iteration.
  - ACTION: ask user "disable matomo and email providers? [Y/n]".
  - DEFAULT: yes (disable both).
  - SKIP ASK: only if user already answered explicitly in this iteration.
  - ON YES: pass `SERVICES_DISABLED="matomo,email"` verbatim to every deploy command. The value is a comma-separated list of provider keys, NOT a glob, NOT a `web-app-*.services.*` path.
  - ON NO: omit the variable entirely.
  - SIDE EFFECT (yes): inventory initializer auto-removes `web-app-matomo` and `web-app-mailu` provider roles. Do NOT list them in `APPS`.
  - PERSIST: record answer at top of iteration. Reuse for all subsequent deploys without re-asking.
- You MUST run `make test` before every deploy. Only proceed with the deploy if all tests pass.
- Unless the user explicitly says to reuse the existing setup, you MUST start once with `make deploy-fresh-purged-apps APPS=<roles> FULL_CYCLE=true` to establish the baseline inventory and clean app state. `FULL_CYCLE=true` adds the async update pass (pass 2) and MUST stay on unless the user explicitly asks to skip it.
- You MUST NOT run more than one deploy command at the same time. Deployments MUST be executed serially, never in parallel.
- To speed up debugging, you MAY pass multiple apps at once, e.g. `make deploy-fresh-purged-apps APPS="<roles> <roles>" FULL_CYCLE=true`.
- After that, you MUST use `make deploy-reuse-kept-apps APPS=<roles>` for the default edit-fix-redeploy loop.
- Do NOT rerun `make deploy-fresh-purged-apps APPS=<roles> FULL_CYCLE=true` just because a deploy failed or you changed code. That restarts the stack unnecessarily and burns time.
- If the same failure still reproduces on the reuse path and you want to test whether app entity state is involved, use `make deploy-reuse-purged-apps APPS=<roles>` once.
- After that targeted purge check, you MUST return to `make deploy-reuse-kept-apps APPS=<roles>`.
- Only go back to `make deploy-fresh-purged-apps APPS=<roles> FULL_CYCLE=true` if you have concrete evidence that the inventory or host stack is broken, or you intentionally need a fresh single-app baseline again.
- Network or DNS failures during a local deploy count as concrete evidence that the host stack is broken. In that case, the next retry MUST be `make deploy-fresh-purged-apps APPS=<roles> FULL_CYCLE=true`.
- If you need to validate the single-app init/deploy path separately, use `make deploy-fresh-kept-apps APPS=<roles>`.

## Matrix variants

For the matrix-variant mechanism (folder layout, round semantics, `--variant` / `--full-cycle` flags) see [variants.md](../../../contributing/design/variants.md). The agent-side iteration rules below assume that mechanism as background.

- Before you start a Role Loop on a matrix-variant role, you MUST decide if the iteration targets the FULL matrix (validates every variant) or ONE specific variant (focused debug). State the choice explicitly before the first deploy.
- For focused debug on variant `<idx>`, you MUST pin `VARIANT=<idx>` on every command in the iteration. Mixing pinned and unpinned commands silently retargets a different folder.
- Default focused-debug recipe: `VARIANT=<idx> make deploy-fresh-purged-apps APPS=<role> FULL_CYCLE=true` once for the variant baseline, then `VARIANT=<idx> make deploy-reuse-kept-apps APPS=<role>` for the edit-fix-redeploy loop.
- If a reuse target aborts with "inventory not found", you MUST add `VARIANT=<idx>` and re-run; do NOT work around the error by re-creating the unsuffixed folder by hand.
- For FULL-matrix iteration, omit `VARIANT=`. If any round fails, capture WHICH round was the last successful one so the next redeploy can pin `VARIANT=<that-idx>` to it.
- When debugging cross-variant interaction (for example "the multisite variant breaks because single-site state was not purged"), reproduce with the FULL matrix once, then pin `VARIANT=<failing-idx>` and iterate the fix. Re-run the FULL matrix only when you believe the fix is complete.

## Certificate Authority

- If the website uses locally deployed certificates, you MUST run `make trust-ca` before you inspect it in a browser. Otherwise the browser will warn about the local CA and the inspection will not be reliable.
- After `make trust-ca`, you MUST restart the browser so it picks up the updated trust store.
- If `make trust-ca` fails due to missing root permissions, you MUST use the alternative syntax `curl -k` (or `wget --no-check-certificate`) to skip certificate validation when checking URLs from the command line instead of fixing the trust store.

## Inspect

- Before you redeploy, you MUST complete all available inspections first. Check the live local output, local logs, and current browser state so the original state stays visible.
- To inspect files or run commands inside a running container, use `make exec`.
- When a local deploy fails, you SHOULD first inspect and, where practical, validate a fix inside the running container with `make exec` before starting another deploy. Use that live investigation to identify the concrete root cause and save iteration time.
- Once the root cause is understood, you MUST apply the real fix in the repository files and then continue the redeploy loop with the usual commands from this page. In-container fixes are only for diagnosis or short validation and MUST NOT replace the repo change.
