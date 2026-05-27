# Role Dependency Tests 🔗

Integration tests that enforce invariants of the role dependency graph expressed via `meta/main.yml`: declared `dependencies:` targets MUST exist, the `dependencies:` graph MUST be acyclic, and meta dependencies MUST NOT be declared when a guarded `include_role` / `import_role` would suffice.

Tests in this directory MUST only cover `meta/main.yml`'s `dependencies:` key. Checks tied specifically to `galaxy_info.run_after` (self-references, reference existence, run-after cycles) MUST live under [`../services/run_after/`](../services/run_after/). Generic structural role checks (folder names, presence of `meta/main.yml`, include target existence) MUST live two levels up under `tests/integration/roles/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../../docs/contributing/actions/testing/integration.md).
