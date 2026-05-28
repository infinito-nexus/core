# Local Deploy 🚀

Contributor guidance for running deploys against a local development stack on your workstation. For production deploy guidance see the [Deploy Guide](../../administration/deploy.md). For the agent-driven role iteration loop see [role.md](../../agents/action/iteration/role.md). For the matrix-variant mechanism that this page references throughout see [variants.md](../design/variants.md).

## Entry Points 🧭

Two layers exist for invoking a local deploy:

| Layer | When to use |
|---|---|
| `make compose-deploy` in the [Makefile](../../../Makefile) | Default. Single entry point routed by [main.sh](../../../scripts/tests/deploy/local/deploy/main.sh). For the full Make-variable surface (`apps`, `mode`, `purge`, `type`, `bundles`, `disable`, `full_cycle`, `variant`) run `make help target=compose-deploy`. |
| `infinito administration deploy development <subcommand>` (Python CLI) | Direct invocation when you need a flag the make target does not expose, or when you script multi-step flows yourself. |

The make target ultimately calls the same CLI, so any behaviour described here applies to both.

## First-Run Baseline 📦

Use `mode=reinstall` to bring up a clean slate (cycles the dev stack and purges shared entities first):

```bash
make compose-deploy mode=reinstall apps="<role> <role>" full_cycle=true
```

- `full_cycle=true` adds the async update pass (pass 2) and SHOULD stay on for the baseline. The behaviour, per-variant interleaving, and `--full-cycle` flag mechanics are documented in [variants.md](../design/variants.md).
- The router runs init, then deploy. Init materialises the inventory under `${INFINITO_INVENTORY_DIR}` (resolved by `make dotenv` via [resolve.sh](../../../scripts/inventory/resolve.sh); see [variables.md](../environment/variables.md)).
- For roles with a `roles/<role>/meta/variants.yml` the init step produces one inventory folder per variant; the deploy step iterates them. Folder layout, round semantics, cleanup rules, and the link to the file-format reference live in [variants.md](../design/variants.md).

## Edit / Fix / Redeploy Loop 🔁

Default redeploy after a local code change:

```bash
make compose-deploy mode=update apps="<role>"
```

- Reuses the existing inventory, keeps app state, runs the deploy only.
- For multi-variant roles you MUST set `variant=<idx>` (see [Pinning A Single Variant](#pinning-a-single-variant-)) so the reuse path targets the round's folder. Without `variant=`, the reuse target points at `<INFINITO_INVENTORY_DIR>` which only exists for single-variant roles.

If the reuse path keeps reproducing the same failure and you want to test whether app entity state is involved:

```bash
make compose-deploy mode=update apps="<role>" purge=true
```

This purges the app's containers + volumes + Ansible-managed state on the host, then re-deploys. Use it once, then return to `mode=update` without `purge=true`. Do NOT loop with `purge=true`; if the failure survives a single purge it is not a state issue.

Only return to `mode=reinstall` when you have concrete evidence that the inventory or the host stack itself is broken (for example DNS or network failures during the deploy).

## Pinning A Single Variant 🎯

For multi-variant roles you MAY restrict any of the `make compose-deploy` invocations above (and the dev CLI subcommands) to a single matrix round by setting `variant=<idx>`:

```bash
# Variant 1 baseline only (no full matrix):
make compose-deploy mode=reinstall apps="<role>" full_cycle=true variant=1

# Edit-fix-redeploy loop pinned to that variant:
make compose-deploy mode=update apps="<role>" variant=1
```

Pinning is sticky: when iterating with `variant=<idx>`, you MUST set it on every command in the iteration. Mixing pinned and unpinned commands silently retargets a different folder. The full semantics (single-folder mode, no inter-round cleanup, out-of-range error) live in [variants.md](../design/variants.md).

## Direct CLI Invocation ⚙️

When you need a flag the make wrappers do not expose, call the dev CLI directly:

```bash
infinito administration deploy development init   --inventory-dir "${INFINITO_INVENTORY_DIR}" --apps "<role>"
infinito administration deploy development deploy --inventory-dir "${INFINITO_INVENTORY_DIR}" --apps "<role>" [--variant <idx>] [--debug]
```

- `--inventory-dir` is always the BASE path. The wrapper appends the `-<round>` suffix internally for matrix folders.
- `--variant <idx>` pins to one round (same semantics as the `variant=` make arg).
- The CLI prints the planned folder list at init time and the per-round summary at deploy time, so you can confirm the matrix shape before any work happens.

## Inspect Live State 🔍

Use [`make compose-exec`](../../../Makefile) to drop into the running container shell. The repo is mounted at `/opt/src/infinito`, so code changes are visible immediately. Inspect logs and current state BEFORE redeploying so the failing snapshot stays available.

For TLS-enabled local sites, run [`make network-trust-ca`](../../../Makefile) once after the first deploy and restart the browser; alternatively use `curl -k` on the command line.

## Reference Files 📌

| File | Purpose |
|---|---|
| [Makefile](../../../Makefile) | The `deploy` router target and `make compose-exec` / `make network-trust-ca` helpers. |
| [dev CLI tree](../../../cli/administration/deploy/development/) | Python CLI for init, deploy, up, down, exec, etc. |
| [`make dotenv`](../../../Makefile) | Resolves `INFINITO_INVENTORY_DIR`, `INFINITO_INVENTORY_FILE`, and `INFINITO_INVENTORY_VARS_FILE` into `.env` for the dev CLI (see [variables.md](../environment/variables.md)). |
| [local deploy scripts](../../../scripts/tests/deploy/local/) | Bash glue behind the make targets (fresh / reuse / purge variants). |
| [variants.md](../design/variants.md) | Matrix-variant deep dive. |
| [role.md](../../agents/action/iteration/role.md) | Role-iteration loop for agents. Recommended reading even for human contributors. |
