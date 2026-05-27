# Meta-Layout Integration Tests 🗂️

Integration tests for cross-cutting metadata that describes the project itself: role categories, CLI entrypoints, domain declarations, and GitHub-side CI/CD artefacts (workflows, Dependabot).

Each child directory pins one meta surface; see the per-directory README for scope. Per-role structural rules (`meta/main.yml`, `meta/services.yml`, includes) live under [`roles/`](../roles/); infrastructure layout lives under [`infrastructure/`](../infrastructure/).

For framework and `make test-integration` usage see [integration.md](../../../docs/contributing/actions/testing/integration.md).
