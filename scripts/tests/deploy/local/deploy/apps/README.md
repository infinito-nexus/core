# Apps Deploy Flows 📦

This directory holds the local deploy flows for one or more applications.
For the higher-level overview, prerequisites, and naming rationale, see [README.md](../README.md).

## Layout 🗂️

The subtree splits by user intent (the verb) and scope:

| Verb folder | Inventory | Stack cycle | Entity purge |
|---|---|---|---|
| `initialize/` | fresh | no | no |
| `reinstall/` | fresh | yes (down + up) | yes (shared entities) |
| `update/` | reuse | no | no |

Each verb folder MUST contain `all.sh` for every discovered application and MAY contain `selection.sh` for one or more apps passed via `apps` (or as a positional argument where supported).

## Conventions 📐

- The verb folder name expresses the deploy intent. The script name expresses the scope.
- `all.sh` discovers applications on the host via `scripts/meta/resolve/apps.sh` and runs against the full list.
- `selection.sh` requires the caller to supply the application set explicitly.
- Stack state (containers, volumes) and the inventory directory stay on disk after every flow in this subtree.
