# Update Pipeline 🔄

Shell helpers that drive the scheduled `Update: Versions` workflow.

## Scope 📋

This directory contains the helpers invoked by [update.yml](../../../.github/workflows/update.yml) to bump pinned upstream versions and open a pull request once per day. The helpers are thin wrappers: the image-version and repository-ref bumpers delegate to Python CLIs under [cli/contributing/](../../../cli/contributing/) that scan `roles/*/meta/services.yml` and rewrite version pins in place; the PR-open helper commits, force-pushes the update branch, and creates or refreshes the PR via `gh`. Helpers MUST NOT be called from workflows other than `Update: Versions`; the `CI_ENABLE_AUTO_UPDATES` gate is enforced once, at the workflow's job level, and bypassing it from another caller would create PRs even when auto-updates are intentionally disabled.

Each shim MUST resolve the repository root relative to its own location so it can run from any working directory, MUST forward arguments to the underlying CLI so `--dry-run` and similar flags keep working from the shell, and MUST exit non-zero on CLI failure so the workflow surfaces the error.

For the workflow catalog see [workflows.md](../../../docs/contributing/tools/github/actions/workflows.md). For the repository variable that gates the workflow see [configuration.md](../../../docs/contributing/tools/github/actions/configuration.md). For the App-token secrets that the PR-opening step requires see [secrets.md](../../../docs/contributing/tools/github/actions/secrets.md).
