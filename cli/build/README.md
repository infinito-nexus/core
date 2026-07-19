# Build 🏗️

Build-time generators that materialise role include lists, dependency graphs, and tree visualisations from the role metadata in `roles/`.

## `readme`

`python -m cli.build.readme [roles...] [--override] [--update-cosmos] [--check]` generates or completes role `README.md` files from `templates/roles/README.md.j2` (the section schema single source of truth). It derives the `## Cosmos` mermaid diagram from `meta/services.yml`, the `## Quick Setup` commands from the role id, and the `## Credits` block from `meta/main.yml`. Prose sections are never rewritten.

- default: add only the managed sections that are missing.
- `--override`: regenerate every managed section in place.
- `--update-cosmos`: regenerate only the Cosmos diagram.
- `--check`: write nothing; exit non-zero if any README would change.

Make wrappers: `make readme-generate [role=<id>] [override=true] [cosmos=true]` and `make readme-check`.
