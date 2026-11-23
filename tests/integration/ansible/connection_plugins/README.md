# Connection Plugin Tests 🔌

Integration tests that exercise custom Ansible connection plugins end-to-end through real playbook runs against a stand-in `docker` executable, so no real container is involved.

Tests in this directory MUST only cover connection plugins shipped under `plugins/connection/`. Tests that validate action, filter or lookup plugins MUST live elsewhere under `tests/integration/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
