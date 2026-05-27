# Pull Request Resolvers 🔀

This directory contains Pull Request-specific resolver scripts used by the PR workflow.

Examples in this folder:

- `scope.sh` resolves whether a Pull Request is agents-only, documentation-only, or full scope
- `branch_prefix.sh` validates that the PR branch prefix matches the detected scope; see [branch.md](../../../../docs/contributing/artefact/git/branch.md) for the authoritative list of valid prefixes and their CI impact
- `merge_ref.sh` resolves the merge ref used for forked PR workflows

These scripts keep PR scope detection, branch-prefix validation, and fork merge-ref resolution together in one place.
