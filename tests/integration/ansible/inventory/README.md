# Inventory Tests 📒

Integration tests for `utils/manager/inventory/InventoryManager` and related inventory-schema machinery: transitive provider-role resolution, schema apply, vault scalar round-trip.

Tests in this directory MUST only cover inventory construction and schema-apply logic. Tests for provider resolution at the lookup layer MUST live under [`lookups/`](../lookups/); tests for the CLI wrappers that drive InventoryManager MUST live under [`cli/`](../../meta/cli/).

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
