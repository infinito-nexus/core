# Repository Cleanup 🧹

Shell helpers for scheduled repository-maintenance workflows that prune stale GitHub resources.

## Scope 📋

Helpers in this directory are invoked by maintenance workflows under [`.github/workflows/`](../../../.github/workflows/).
They may call the GitHub API through `gh`, but MUST keep destructive selection criteria inside scripts so workflow files remain orchestration-only.
CI image cleanup derives distro-specific package names from `INFINITO_DISTROS`, whose default comes from [default.env](../../../default.env) through the environment loader.

For the workflow catalog that drives these calls see [workflows.md](../../../docs/contributing/tools/github/actions/workflows.md).
