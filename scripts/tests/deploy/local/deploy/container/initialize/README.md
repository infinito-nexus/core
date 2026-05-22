# Initialize 🌱

In-container half of the fresh all-apps deploy.
Runs entry bootstrap, creates the inventory from the env-injected app list, and then invokes the dedicated deploy in one container session.

## Entry Point 🚪

| Entry point | Scope |
|---|---|
| `all.sh` | every app id listed in `APPS_CSV` (typically the full host-discovered set) |

## Required Environment 🔑

| Variable | Purpose |
|---|---|
| `INFINITO_SRC_DIR` | absolute path to the bind-mounted repo root inside the container |
| `INFINITO_INVENTORY_DIR` | absolute base inventory dir (no trailing slash) |
| `INFINITO_INVENTORY_FILE` | absolute path to `${INFINITO_INVENTORY_DIR}/devices.yml` |
| `INFINITO_INVENTORY_VARS_FILE` | repo-relative dev vars file |
| `APPS_CSV` | comma-separated app id list passed to `--include` |
| `APPS_COUNT` | length of `APPS_CSV` (echoed for log clarity) |
| `INFINITO_LIMIT_HOST` | Ansible limit, typically `localhost` |
| `RUNTIME_VARS_JSON` | JSON object passed verbatim to `--vars` |

For the host wrapper that injects these, see [apps/initialize/all.sh](../../apps/initialize/all.sh).
