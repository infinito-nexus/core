# Update ♻️

Redeploy the selected applications against the already-initialized local inventory.
The flow does not bring the development stack down or up and does not purge entities, so it MUST be preceded by a successful run from [initialize/](../initialize/README.md) or [reinstall/](../reinstall/README.md).

## Entry Points 🚪

| Entry point | Scope |
|---|---|
| `all.sh` | every discovered application from the existing inventory |
| `selection.sh` | one or more apps passed via `apps` |

## Optional Pinning 📌

Pass `variant=<idx>` to `make compose-deploy` to pin the redeploy to a specific matrix round.
The script then resolves the inventory under `${INFINITO_INVENTORY_DIR}-<idx>`.
Without `variant=` the unsuffixed path is used, which is correct for single-variant deploys.
