# Role Structure Tests 📚

Integration tests that enforce structural invariants of every role under `roles/`: folder-name conventions and `include_tasks` / `import_tasks` target existence.

Tests in this directory MUST only cover role-level structural rules (folder naming, role-name regex). `meta/main.yml` presence and field checks MUST live under [`meta/`](meta/). Dependency-graph checks (self-, circular, unnecessary dependencies, `run_after`) MUST live under [`meta/dependencies/`](meta/dependencies/) (and the sibling [`meta/services/run_after/`](meta/services/run_after/)). Application-specific role rules (web-app README, `applications[...]` / `group_names` usage, `application_id` identity) MUST live under [`applications/`](applications/). `run_once_<role>` flag lifecycle checks MUST live under [`run_once/`](run_once/). Block-level `when:` hygiene (guard blocks, duplication, size) MUST live under [`when/`](when/). `include_tasks` / `import_tasks` / `include_role` / `import_role` target existence MUST live under [`includes/`](includes/). Compose- or handler-specific checks MUST live in their respective topical clusters.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../docs/contributing/actions/testing/integration.md).
