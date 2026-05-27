# CLI Tests 🖥️

Integration tests for the `cli/` package: subcommand discovery and `--help` smoke tests for every invokable CLI entrypoint.

Tests in this directory MUST only cover CLI-level behavior (argument parsing, `--help`, dispatcher). Tests for the libraries that CLIs import MUST live under `tests/unit/` or the relevant topical cluster.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
