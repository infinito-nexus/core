# Naming Lint 🏷️

Tests that enforce the `test_*.py` prefix convention and the rule that every `test_*.py` file lives under `tests/` and contains at least one runnable `unittest.TestCase`.

Tests in this directory MUST only cover file-naming and test-discovery contracts. Other Python conventions MUST live under [`python/`](../../filesystem/python/).

For framework and `make test-lint` usage see [lint.md](../../../../docs/contributing/actions/testing/lint.md).
