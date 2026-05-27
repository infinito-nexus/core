# Playbook Tests 🎬

Integration tests for playbook-level wiring: `tasks/stages/**`, `tasks/groups/*-roles.yml`, invokable-path coverage, and the dispatch between them.

Tests in this directory MUST only cover rules about how playbooks invoke role groups and how the invokable-paths filter maps to stages. Tests for role-internal `meta/main.yml` MUST live under [`roles/meta/`](../../roles/meta/); tests for include/import target existence MUST live under [`roles/includes/`](../../roles/includes/).

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
