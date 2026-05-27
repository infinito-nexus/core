# Settings Lint ⚙️

Configuration-file invariants: `.claude/settings.json` permission lists stay sorted.

Tests in this directory MUST only cover repository settings files (Claude Code config, IDE rule files, agent permission catalogues). Code conventions MUST live elsewhere under `tests/lint/repository/`.

For framework and `make test-lint` usage see [lint.md](../../../../docs/contributing/actions/testing/lint.md).
