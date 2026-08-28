# Dependencies Lint 📦

Python packaging and dependency-reference rules: `pyproject.toml` requirement coverage, ban on stale `requirements/NNN-…` numbers in code, the deprecated-`pkgmgr` warning, and Galaxy/git parity of the Ansible collection requirements (suppression rule key `galaxy-git-parity`).

Tests in this directory MUST only cover dependency declarations and requirement cross-references. Other Python source patterns MUST live under [`python/`](../../filesystem/python/).

For framework and `make test-lint` usage see [lint.md](../../../../docs/contributing/actions/testing/lint.md).
