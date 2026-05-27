# Scripts 🧰

This page covers file placement rules inside the repository `scripts/` tree.
For workflow-specific extraction rules, see [workflow.md](files/github/workflow.md). For Python helper placement, see [utils.md](utils.md).

## Allowed file types 📋

- Tracked files under `scripts/` MUST use the `.sh` extension.
- `README.md` files MAY exist under `scripts/` as documentation-only exceptions.
- Python, YAML, JSON, and other helper file types MUST NOT be stored under `scripts/`.

## Scope 🎯

- The `scripts/` tree MUST contain executable shell entry points and shell helper files only.
- If automation logic is not shell-based, it MUST live outside `scripts/` and be called from a `.sh` wrapper when needed.
