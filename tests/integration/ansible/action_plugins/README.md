# Action Plugin Tests 🧩

Integration tests that exercise custom Ansible action plugins end-to-end through real playbook runs (e.g. retry behavior of `uri` / `get_url` wrappers).

Tests in this directory MUST only cover action plugins shipped under `plugins/action/` and their retry/error semantics. Tests that validate filter plugins, lookup plugins, or unrelated role logic MUST live elsewhere under `tests/integration/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
