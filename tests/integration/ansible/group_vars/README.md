# Group Vars Tests 📦

Integration tests that validate the contents of `group_vars/all/*.yml`: no Jinja recursion cycles, consistent user/application cross-references, and internal schema rules.

Tests in this directory MUST only cover `group_vars/` content. Tests for role-local vars, ports, networks, or domain registration MUST live under their topical cluster elsewhere in `tests/integration/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
