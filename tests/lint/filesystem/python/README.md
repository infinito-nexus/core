# Python Lint 🐍

Python-specific code conventions: unittest import shape, `PROJECT_ROOT` usage, ban on raw `os.walk`/`Path.rglob`/uncached `read_text`, `noqa` marker hygiene, redundant boolean patterns, and self-path-reference avoidance.

Tests in this directory MUST only cover Python source patterns. Dependency declarations MUST live under [`dependencies/`](../../repository/dependencies/); YAML/Jinja patterns MUST live under [`yaml/`](../../repository/yaml/).

For framework and `make test-lint` usage see [lint.md](../../../../docs/contributing/actions/testing/lint.md).
