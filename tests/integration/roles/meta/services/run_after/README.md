# `run_after` Dependency Tests ⏭️

Integration tests that enforce invariants of `galaxy_info.run_after` in each role's `meta/main.yml`: every referenced name MUST resolve to an existing role directory, no role MUST list itself in `run_after`, and the resulting ordering graph MUST be acyclic.

Tests in this directory MUST only cover `run_after` semantics. Checks that target the `dependencies:` key MUST live in the sibling [`../../dependencies/`](../../dependencies/) cluster; broader `meta/services.yml` shape checks MUST live one level up in [`../`](../).

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../../../docs/contributing/actions/testing/integration.md).
