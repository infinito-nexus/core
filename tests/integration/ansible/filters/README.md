# Filter Plugin Tests 🔍

Integration tests for custom Jinja filter plugins under `plugins/filter/` and `roles/*/filter_plugins/`: every filter referenced in templates MUST be defined, and filters MUST behave correctly end-to-end (e.g. `strong_password`, `dotenv_quote`).

Tests in this directory MUST only cover filter-plugin definition and usage. Action-plugin, lookup-plugin, and template-rendering tests MUST live elsewhere under `tests/integration/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
