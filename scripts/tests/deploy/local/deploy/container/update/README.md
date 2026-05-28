# Update ♻️

In-container halves of the update redeploy flows.
Each script reuses an already-initialized inventory and runs `infinito administration deploy dedicated` against it; no inventory creation, no entity purge, no stack down/up.

## Entry Points 🚪

| Entry point | Scope |
|---|---|
| `all.sh` | every app in the existing inventory (host wrapper recomputes the list for log clarity) |
| `selection.sh` | one or more apps passed via `apps` |

## Required Environment 🔑

`all.sh` requires:

| Variable | Purpose |
|---|---|
| `INFINITO_SRC_DIR` | absolute path to the bind-mounted repo root inside the container |
| `INFINITO_INVENTORY_FILE` | absolute path to `<inv>/devices.yml` |
| `INFINITO_INVENTORY_PASSWORD_FILE` | absolute path to `<inv>/.password` |
| `INFINITO_LIMIT_HOST` | Ansible limit, typically `localhost` |
| `INFINITO_DEBUG` | `true` or `false`; appends `--debug` when true |

`selection.sh` requires:

| Variable | Purpose |
|---|---|
| `INFINITO_SRC_DIR` | absolute path to the bind-mounted repo root inside the container |
| `INFINITO_INVENTORY_FILE` | absolute path to `<inv>/devices.yml` |
| `apps` | space-separated app id list passed to `--id` |
| `INFINITO_DEBUG` | `true` or `false`; appends `--debug` when true |

For the host wrappers that inject these, see [apps/update/all.sh](../../apps/update/all.sh) and [apps/update/selection.sh](../../apps/update/selection.sh).
