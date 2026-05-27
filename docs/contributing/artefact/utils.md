# Utilities 🐍

This page covers file placement rules inside the repository `utils/` tree.
For shell-script placement rules, see [scripst.md](scripst.md).

## Allowed file types 📋

- Tracked files under `utils/` MUST use the `.py` extension.
- `README.md` files MAY exist under `utils/` as documentation-only exceptions.
- Utility code under `utils/` MUST be grouped into folders or namespaces when multiple helpers share one domain.

## Scope 🎯

- The `utils/` tree MUST contain Python helper modules and helper packages only.
- Shell scripts, workflow wrappers, and non-Python helper assets MUST NOT be stored under `utils/`.
