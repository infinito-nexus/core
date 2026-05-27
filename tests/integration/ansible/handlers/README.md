# Handler Tests 🛎️

Integration tests that enforce contracts between tasks and handlers: every `notify:` target MUST resolve to an existing handler name or `listen:` alias, and handler names MUST be static strings (no Jinja templating).

Tests in this directory MUST only cover handler invocation and naming rules. Tests for task-file includes, run-once flags, or block structure MUST live elsewhere under `tests/integration/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
