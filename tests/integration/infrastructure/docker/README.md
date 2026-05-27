# Docker Tests 🐳

Integration tests that validate Docker-level contracts for role services: compose template includes, declared service keys, and image/version validity.

Tests in this directory MUST only cover Docker-specific semantics (images, tags, compose-service configuration). Generic compose-structure rules MUST live under `tests/integration/compose/`, and backup-related checks MUST live under `tests/integration/backups/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
