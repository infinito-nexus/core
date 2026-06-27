# Resolve Scripts

This directory contains scripts that resolve metadata and derived values used by the project.

- 🧩 Derive runtime values from repository and workflow context
- 🔍 Resolve identifiers, references, and computed inputs
- 🗂️ Keep lookup and resolution logic grouped in one place

Examples in this folder and its subfolders:

- `repository/name.sh` resolves the concrete repository name once for callers
- `repository/owner.sh` resolves the concrete repository owner once for callers
- See [pr/README.md](pr/README.md) for the Pull Request-specific resolvers.

The scope of this folder is value resolution.
Build, release, and wait-oriented behavior should stay in their dedicated script directories.
