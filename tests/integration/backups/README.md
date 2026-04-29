# Backup Tests 💾

Integration tests that enforce the contract between a role's `services[*].backups.*` configuration and the backup infrastructure (enabled flag, `no_stop_required`, image consistency).

Tests in this directory MUST only cover backup-related configuration consistency. Tests that validate unrelated compose structure, port mappings, or runtime behavior MUST live elsewhere under `tests/integration/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../docs/contributing/actions/testing/integration.md).
