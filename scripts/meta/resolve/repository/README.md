# Repository Resolve Scripts

This directory contains repository-specific resolvers used across workflows and shell helpers.

- `name.sh` resolves the concrete repository name once for callers
  It prefers explicit env overrides (`INFINITO_IMAGE_REPOSITORY`, `REPO_PREFIX`) before GitHub or git metadata.
- `owner.sh` resolves the concrete repository owner once for callers
- `primary.sh` resolves the primary checkout, the same path from every worktree

These scripts are the SPOT for repository identity resolution.
