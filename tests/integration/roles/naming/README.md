# Role Naming Tests 🏷️

Integration tests that enforce role naming conventions: folder names match the declared category prefix (`web-app-*`, `web-svc-*`, `sys-*`, …), and roles do not collide on canonical identifiers.

Tests in this directory MUST only cover role-folder and role-name conventions. Per-role structural rules (`meta/`, `tasks/`, `templates/`) MUST live under the sibling clusters [`meta/`](../meta/), [`when/`](../when/), or [`run_once/`](../run_once/).

For framework and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
