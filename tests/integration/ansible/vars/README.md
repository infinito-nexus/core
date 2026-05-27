# Vars & Defaults Tests 📐

Integration tests for cross-role variable and defaults hygiene: `TOP_LEVEL_CONSTANT` uniqueness across `roles/*/vars/**`, `roles/*/defaults/**`, and `group_vars/**`; and the prohibition against overriding Ansible facts via `vars:` or `set_fact:`.

Tests in this directory MUST only cover rules about variable DEFINITION hygiene (uniqueness, naming, override prohibitions). Rules about variable USAGE in Jinja templates MUST live under [`jinja/`](../jinja/).

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
