# Lookup Plugin Tests 🔎

Integration tests for the custom Ansible lookup plugins under `plugins/lookup/`: config-path validation against role schemas and runtime caching performance.

Tests in this directory MUST only cover lookup-plugin behavior (schema validation of `lookup('config', …)` paths, caching semantics, performance smoke). Pure unit tests for a single lookup plugin's return values MUST live under `tests/unit/plugins/lookup/`.

[`config/`](config/) holds the `lookup('config', …)` path-validation suite. The four classifier tests share a single cached project scan exposed by `_scan.iter_matches` and `_scan.get_context`; validation helpers live in `_validate.py`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
