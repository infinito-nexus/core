# Entity Purge 🗑️

Entity-keyed purge primitives for stack-level cleanup inside the running container.

For the canonical Make target index that invokes these helpers, see [make.md](../../../../docs/contributing/tools/make.md).

## Entry Points 🎯

| Script | What it does | Key inputs |
|---|---|---|
| `compose.sh` | Stops the compose stack and removes volumes. | Stack names |
| `db.sh` | Drops or truncates the backing database. | Stack names, `--wipe-data-only` |
| `dir.sh` | Removes the stack directory and its volumes. | Stack names |
| `nginx.sh` | Removes the per-domain nginx vhost files (http + https) belonging to every app under the entity. Thin wrapper around [nginx_vhosts.py](../../../../utils/cleanup/nginx_vhosts.py). | Stack names |
| `network.sh` | Drops the per-entity default Docker network when `compose.sh` left it behind with the wrong / empty `com.docker.compose.network` label (typical between matrix-deploy rounds). Skips removal when the network still has active container endpoints, so shared-service networks (svc-db-mariadb, svc-db-postgres, …) stay in place while their provider container is up. The global `docker network prune -f` sweep that catches orphans whose names do NOT match the entity is run once by the orchestrator [apps.sh](../apps.sh) after the entity loop. Idempotent. | Stack name |

These primitives are entity-keyed.
The app-keyed orchestrator [apps.sh](../apps.sh) maps app ids to entities and drives them in sequence alongside the token-store wipe in [tokens.py](../../../../utils/cleanup/tokens.py).
