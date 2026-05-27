# Jinja Lints 🪄

Lint tests that enforce correct Jinja2 filter and lookup composition in Ansible templates and task definitions.

Tests in this directory MUST only cover Jinja2 expression composition rules.
Rules that validate where dotted-path targets are declared live in the sibling `../variables/` directory.

- `test_no_lookup_config_jinja_default.py` forbids `lookup('config', application_id, 'path') | default(X)`. The two-term `config` lookup raises on a missing key, so the Jinja `default(...)` filter never fires; the fallback MUST be passed as the lookup's third argument instead.

For framework, directory layout, and `make test-lint` usage see [lint.md](../../../../docs/contributing/actions/testing/lint.md).
