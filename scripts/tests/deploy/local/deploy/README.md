# Local Deploy Scripts

This directory holds the executable local deploy flows under `scripts/tests/deploy/local/deploy/`.

For other local helpers, use [../README.md](../README.md).
For the canonical Make target index that invokes these helpers, see [make.md](../../../../../docs/contributing/tools/make.md).

## Prerequisites

- Run commands from the repository root.
- Docker and Docker Compose are available locally.
- `jq` is installed for the app-discovery step in `apps/initialize/all.sh`.
- If you run scripts directly, load the defaults with `source scripts/meta/env/all.sh`.

## Naming

The `apps/` subtree is split by verb (the user intent) and scope:

- `initialize/` creates or refreshes the inventory; existing entity state is kept.
- `reinstall/` recreates the inventory and purges existing entities first.
- `update/` reuses the already-initialized inventory.
- `all.sh` covers every discovered application; `selection.sh` covers one or more apps passed via `apps` (or a positional argument).

The `bundles/` subtree mirrors the same axes for inventory bundles (`fresh.sh` ≈ initialize, `update.sh` ≈ update).

The `container/` subtree holds the in-container halves invoked by the host wrappers and follows the same verb/scope layout; see [container/](container/README.md).

## Entry Points

| Entry point | What it does | Key inputs | Notes |
|---|---|---|---|
| `apps/initialize/all.sh` | Discovers apps, creates `devices.yml`, and deploys all discovered apps. | `INFINITO_DISTRO`, `INFINITO_DEPLOY_TYPE`, `INFINITO_INVENTORY_DIR` | Fresh all-app inventory path. |
| `apps/initialize/selection.sh <app-id>` | Creates `devices.yml` for one or more apps and deploys them. | `apps=<app-id>` | Init and deploy path for a specific app set. |
| `apps/reinstall/selection.sh` | Recreates `devices.yml` and deploys one or more apps twice with `ASYNC_ENABLED=false` and `ASYNC_ENABLED=true`. | `INFINITO_DISTRO`, `INFINITO_INVENTORY_DIR`, `INFINITO_DEPLOY_TYPE`, `apps` | Baseline and recovery path; purges entities first. |
| `apps/update/all.sh` | Deploys every app from an existing inventory. | `INFINITO_DISTRO`, `INFINITO_DEPLOY_TYPE`, `INFINITO_INVENTORY_DIR` | Requires `${INFINITO_INVENTORY_DIR}/devices.yml` and `.password`. |
| `apps/update/selection.sh` | Runs a targeted `infinito administration deploy dedicated` for one or more apps. | `apps`, `INFINITO_DEPLOY_TYPE`, `INFINITO_CONTAINER`, `INFINITO_DEBUG`, `INFINITO_INVENTORY_DIR` | Reuses `devices.yml`. |
