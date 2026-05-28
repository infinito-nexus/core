# Bundles Deploy Flows 📦

Aggregate one or more inventory bundles into a single `apps` list and run a deploy against the resulting application set.
Bundles live under `inventories/bundles/{servers,workstations}/<name>/inventory.yml` and declare the role groups they activate.

## Entry Points 🚪

| Entry point | Delegates to | Notes |
|---|---|---|
| `fresh.sh` | [apps/reinstall/selection.sh](../apps/reinstall/README.md) | First-run path. Cycles the stack and purges shared entities. |
| `update.sh` | [apps/update/selection.sh](../apps/update/README.md) | Repeat-run path. Reuses the existing inventory; no stack cycle, no purge. |

## Required Environment 🌱

- The `bundles=` make arg (comma-separated bundle names) is REQUIRED for both entry points. The compose-deploy recipe sets the resulting `bundles` env var read by these scripts.
- The remaining variables match the requirements of the delegated script. See its `README.md` for details.

## Resolution ⚙️

`utils.inventory.bundle_apps` reads each named bundle, walks `all.children`, deduplicates the role groups across all bundles, and prints the resulting application list as CSV.
The CSV is exported as `apps` before the delegated script runs.
