# Container Purge 🗑️

Container-local cleanup helpers under `scripts/container/purge/`.

These scripts run inside the local infinito container and remove container-local state only.
For the canonical Make target index that invokes these helpers, see [make.md](../../../docs/contributing/tools/make.md).

## Entry Points 🎯

| Entry point | What it does | Notes |
|---|---|---|
| `apps.sh` | App-keyed orchestrator that maps `$apps` to compose entities, drives `entity/{db,compose,dir}.sh`, and wipes the matching token-store entries via [tokens.py](../../../utils/cleanup/tokens.py). | The host-side wrapper [entity.sh](../../tests/deploy/local/purge/entity.sh) `docker exec`s this script. |
| `web.sh` | Removes nginx and self-signed CA state inside the container. | Called by the local purge wrapper. |
| `entity/` | Entity-keyed primitives. | See [entity/README.md](entity/README.md) for the exact scripts. |
