# System Purge

This directory holds host and system cleanup helpers.
For container-local cleanup helpers, see [../../container/purge/README.md](../../container/purge/README.md).
For the canonical Make target index that invokes these helpers, see [make.md](../../../docs/contributing/tools/make.md).

## Entry Points

| Entry point | What it does | Key inputs | Notes |
|---|---|---|---|
| `system.sh` | Runs the broad low-hardware cleanup pass from the repository root. | `PURGE_WINDOWS_CLEANMGR_SETUP` | Best-effort and safe to rerun. |
| `all.sh` | Runs `system.sh` plus the broader repository cleanup bundle. | none directly; inherits `PURGE_WINDOWS_CLEANMGR_SETUP` | Best-effort and safe to rerun; container cleanup needs the local stack. |

## Script Map

- all.sh
- [system.sh](system.sh)
