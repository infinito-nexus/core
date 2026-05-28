# Reinstall 🔄

Recreate the inventory and deploy the selected applications after cycling the development stack and purging shared entities.
Use this flow when stale container state or cross-application entities (for example shared analytics) need a clean slate before the deploy.

## Entry Points 🚪

| Entry point | Scope |
|---|---|
| `selection.sh` | one or more apps passed via `apps` |

## Behavior 🧭

- Runs `development down` followed by `development up --when-down` to remove and re-create containers.
- Purges shared entities relevant to the deploy (for example `matomo`).
- Bakes a fresh inventory with `ASYNC_ENABLED=false` and `RUNTIME=dev`.
- Set `full_cycle=true` on `make compose-deploy` to run a second async pass after the initial sync pass.

For the non-destructive equivalent, see [initialize/](../initialize/README.md).
