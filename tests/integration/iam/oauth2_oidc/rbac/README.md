# RBAC Group-Path Tests 🛡️

Integration tests that pin the static contracts around the RBAC group-path layer shared by every OIDC-enabled role.

The `rbac_group_path` lookup plugin is the only sanctioned producer of OIDC group paths in this repository. Tests in this directory MUST cover invariants that protect that contract: callsite shape, role declaration consistency, and the ban on inline `[RBAC.GROUP.NAME, ...] | path_join` constructions introduced by requirement 005.

Tests in this directory MUST NOT cover unrelated OAuth2 or OIDC configuration. Generic OAuth2 / OIDC invariants belong one level up under `oauth2_oidc/`. Port and domain checks belong under `tests/integration/ports/` and `tests/integration/domains/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../../docs/contributing/actions/testing/integration.md).
