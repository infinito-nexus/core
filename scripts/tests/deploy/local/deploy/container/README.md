# Container Deploy Helpers 🐳

This directory holds the in-container halves of the local deploy flows.
Each script runs inside the development compose container (the repo is bind-mounted at `${INFINITO_SRC_DIR}`) and is invoked by a matching host wrapper under [apps/](../apps/README.md).

## Layout 🗂️

The subtree mirrors the host-side `apps/` structure verb by verb and scope by scope:

| Host wrapper | Container half |
|---|---|
| `apps/initialize/all.sh` | `container/initialize/all.sh` |
| `apps/update/all.sh` | `container/update/all.sh` |
| `apps/update/selection.sh` | `container/update/selection.sh` |

Verbs without a container half (`reinstall/`, `apps/initialize/selection.sh`) call the dev CLI directly from the host and do not need a paired in-container helper.

## Conventions 📐

Each script MUST be entered via `cli.administration.deploy.development exec --env KEY=VAL` (or an equivalent `docker exec -e …` invocation) so the host wrapper can inject the required environment.
Each script MUST assert its required env-vars at the top with `: "${VAR:?}"` so missing context surfaces immediately.
Each script MUST `cd "${INFINITO_SRC_DIR}"` before running anything so relative paths resolve against the bind-mounted repo.
Each script SHOULD run `./scripts/docker/entry.sh true` for entry bootstrap before the deploy step.
