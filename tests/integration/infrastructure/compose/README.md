# Compose Tests 🧱

Integration tests that validate Docker Compose templates across roles: every service MUST declare an `image`, and `build:` blocks MUST still carry an image reference. The raw `docker` command guard lives in [`../docker/`](../docker/).

Tests in this directory MUST only cover structural rules of `compose.yml.j2` and related compose artefacts. Tests for image versions, backups, or service-registry semantics MUST live elsewhere under `tests/integration/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
