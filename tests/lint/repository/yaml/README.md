# YAML & Jinja Lint 📐

YAML / Jinja patterns: ban on direct `yaml.safe_load` calls outside `utils.cache.yaml`, and ban on hardcoded `http://` / `https://` protocol literals adjacent to a `lookup(...)` call.

Tests in this directory MUST only cover `.yml` / `.yaml` / `.j2` content patterns. Python source rules MUST live under [`python/`](../../filesystem/python/).

For framework and `make test-lint` usage see [lint.md](../../../../docs/contributing/actions/testing/lint.md).
