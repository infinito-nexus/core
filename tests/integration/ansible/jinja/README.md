# Jinja Template Tests 🧪

Integration tests for `.j2` templates across the repository: syntax validity, include-path resolution, and consistent variable definition and usage.

Tests in this directory MUST only cover Jinja-level concerns (template parsing, `{% include %}` resolution, variable reference/definition symmetry). Filter-plugin tests MUST live under `tests/integration/filters/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
