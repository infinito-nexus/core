# Ansible Integration Tests 🧩

Integration tests for Ansible-native artefacts: action plugins, filter plugins, lookup plugins, handlers, group_vars, inventory, Jinja templates, playbooks, and role-local `vars/` / `defaults/`.

Each child directory pins one Ansible surface; see the per-directory README for scope. Topical concerns that are not Ansible-specific (compose/docker/networks, OAuth2/OIDC, service registry, role-meta layout) live under [`infrastructure/`](../infrastructure/), [`iam/`](../iam/), [`meta/`](../meta/), or [`roles/`](../roles/).

For framework and `make test-integration` usage see [integration.md](../../../docs/contributing/actions/testing/integration.md).
