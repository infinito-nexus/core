# Local Deploy 🚀

Contributor guidance for running deploys against a local development stack on your workstation. For production deploy guidance see the [Deploy Guide](../../administration/deploy.md). For the agent-driven role iteration loop see [role.md](../../agents/action/iteration/role.md). For the matrix-variant mechanism that this page references throughout see [variants.md](../design/variants.md).

## Entry Points 🧭

Two layers exist for invoking a local deploy:

| Layer | When to use |
|---|---|
| `make deploy-*` targets in the [Makefile](../../../Makefile) | Default. Stable, opinionated wrappers tuned for the local-dev / CI-on-laptop flow. |
| `infinito deploy development <subcommand>` (Python CLI) | Direct invocation when you need a flag the make targets do not expose, or when you script multi-step flows yourself. |

The make targets ultimately call the same CLI, so any behaviour described here applies to both.

## First-Run Baseline 📦

Use `deploy-fresh-purged-apps` to bring up a clean slate:

```bash
make deploy-fresh-purged-apps APPS="<role> <role>" FULL_CYCLE=true
```

- `FULL_CYCLE=true` adds the async update pass (pass 2) and SHOULD stay on for the baseline. The behaviour, per-variant interleaving, and `--full-cycle` flag mechanics are documented in [variants.md](../design/variants.md).
- The wrapper runs init, then deploy. Init materialises the inventory under `${INVENTORY_DIR}` (set by [inventory.sh](../../../scripts/meta/env/inventory.sh) via [resolve.sh](../../../scripts/inventory/resolve.sh)).
- For roles with a `roles/<role>/meta/variants.yml` the init step produces one inventory folder per variant; the deploy step iterates them. Folder layout, round semantics, cleanup rules, and the link to the file-format reference live in [variants.md](../design/variants.md).

## Edit / Fix / Redeploy Loop 🔁

Default redeploy after a local code change:

```bash
make deploy-reuse-kept-apps APPS="<role>"
```

- Reuses the existing inventory, keeps app state, runs the deploy only.
- For multi-variant roles you MUST set `VARIANT=<idx>` (see [Pinning A Single Variant](#pinning-a-single-variant-)) so the reuse path targets the round's folder. Without `VARIANT`, the reuse target points at `<INVENTORY_DIR>` which only exists for single-variant roles.

If the reuse path keeps reproducing the same failure and you want to test whether app entity state is involved:

```bash
make deploy-reuse-purged-apps APPS="<role>"
```

This purges the app's containers + volumes + Ansible-managed state on the host, then re-deploys. Use it once, then return to `deploy-reuse-kept-apps`. Do NOT loop on `deploy-reuse-purged-apps`; if the failure survives a single purge it is not a state issue.

Only return to `deploy-fresh-purged-apps` when you have concrete evidence that the inventory or the host stack itself is broken (for example DNS or network failures during the deploy).

## Pinning A Single Variant 🎯

For multi-variant roles you MAY restrict any of the make targets above (and the dev CLI subcommands) to a single matrix round by setting `VARIANT=<idx>`:

```bash
# Variant 1 baseline only (no full matrix):
VARIANT=1 make deploy-fresh-purged-apps APPS="<role>" FULL_CYCLE=true

# Edit-fix-redeploy loop pinned to that variant:
VARIANT=1 make deploy-reuse-kept-apps APPS="<role>"
```

Pinning is sticky: when iterating with `VARIANT=<idx>`, you MUST set it on every command in the iteration. Mixing pinned and unpinned commands silently retargets a different folder. The full semantics (single-folder mode, no inter-round cleanup, out-of-range error) live in [variants.md](../design/variants.md).

## Direct CLI Invocation ⚙️

When you need a flag the make wrappers do not expose, call the dev CLI directly:

```bash
infinito deploy development init   --inventory-dir "${INVENTORY_DIR}" --apps "<role>"
infinito deploy development deploy --inventory-dir "${INVENTORY_DIR}" --apps "<role>" [--variant <idx>] [--debug]
```

- `--inventory-dir` is always the BASE path. The wrapper appends the `-<round>` suffix internally for matrix folders.
- `--variant <idx>` pins to one round (same semantics as the `VARIANT` env-var).
- The CLI prints the planned folder list at init time and the per-round summary at deploy time, so you can confirm the matrix shape before any work happens.

## Inspect Live State 🔍

Use [`make exec`](../../../Makefile) to drop into the running container shell. The repo is mounted at `/opt/src/infinito`, so code changes are visible immediately. Inspect logs and current state BEFORE redeploying so the failing snapshot stays available.

For TLS-enabled local sites, run [`make trust-ca`](../../../Makefile) once after the first deploy and restart the browser; alternatively use `curl -k` on the command line.

## Reference Files 📌

| File | Purpose |
|---|---|
| [Makefile](../../../Makefile) | All `deploy-*` and `make exec` / `make trust-ca` targets. |
| [dev CLI tree](../../../cli/deploy/development/) | Python CLI for init, deploy, up, down, exec, etc. |
| [inventory.sh](../../../scripts/meta/env/inventory.sh) | Resolves `INVENTORY_DIR`, `INVENTORY_FILE`, and `INVENTORY_VARS_FILE` for the dev CLI. |
| [local deploy scripts](../../../scripts/tests/deploy/local/) | Bash glue behind the make targets (fresh / reuse / purge variants). |
| [variants.md](../design/variants.md) | Matrix-variant deep dive. |
| [role.md](../../agents/action/iteration/role.md) | Role-iteration loop for agents. Recommended reading even for human contributors. |
