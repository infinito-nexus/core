# Local Exec Scripts

This directory holds the container execution helpers under `scripts/tests/deploy/local/exec/`.
For other local helpers, use [../README.md](../README.md).
For the canonical Make target index that invokes these helpers, see [make.md](../../../../../docs/contributing/tools/make.md).

## Entry Points

| Entry point | What it does | Key inputs | Notes |
|---|---|---|---|
| `container.sh` | Opens an interactive shell in the running container or runs a one-off command. | `INFINITO_DISTRO`, `INFINITO_CONTAINER`, optional `INSPECT_CMD` or positional args | Uses `docker exec` against the live `infinito` container. |

## Script Map

- [container.sh](container.sh)
