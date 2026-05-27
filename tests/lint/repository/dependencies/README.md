# Dependencies Lint 📦

Python packaging and dependency-reference rules: `pyproject.toml` requirement coverage, ban on stale `requirements/NNN-…` numbers in code, and the deprecated-`pkgmgr` warning.

Tests in this directory MUST only cover dependency declarations and requirement cross-references. Other Python source patterns MUST live under [`python/`](../../filesystem/python/).

For framework and `make test-lint` usage see [lint.md](../../../../docs/contributing/actions/testing/lint.md).
