# Service Registry Tests 🛰️

Integration tests that validate the service registry discovered from `roles/*/config/main.yml`: canonical aliases are consistent, every service key resolves via `plugins/lookup/service.py`, `sys-svc-*` roles carry a `system_service_id` matching their folder, and transitive dependencies (e.g. dashboard → mailu) are declared correctly.

Tests in this directory MUST only cover service-registry semantics. Tests for `application_id` identity MUST live under `tests/integration/roles/applications/id/`, and generic role-structure rules MUST live under `tests/integration/roles/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
