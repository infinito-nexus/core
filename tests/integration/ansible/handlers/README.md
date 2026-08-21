# Handler Tests 🛎️

Integration tests that enforce contracts between tasks and handlers. One file per contract, no second opinion on the same rule:

- [test_invoked.py](test_invoked.py) — every `notify:` MUST resolve to a `listen:` topic (never to a handler name), every `listen:` MUST be notified by someone, and both MUST spell out as `[a-z_-]+`.
- [test_names_static.py](test_names_static.py) — a `listen:`-bearing handler entry MUST carry a static name (no Jinja templating).

Tests in this directory MUST only cover handler invocation and naming rules. Tests for task-file includes, run-once flags, or block structure MUST live elsewhere under `tests/integration/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
