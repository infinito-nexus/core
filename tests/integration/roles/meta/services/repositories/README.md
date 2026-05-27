# Repository Declaration Tests 📦

Integration tests that enforce invariants of repository declarations in `roles/*/meta/services.yml`: every `git clone`-style URL referenced from a role MUST be declared as an entity with a `repository:` key, and any entity that declares `repository:` MUST also pin a `ref:`.

Tests in this directory MUST only cover repository/ref shape rules. Broader `meta/services.yml` invariants live one level up in [`services/`](../).

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../../../docs/contributing/actions/testing/integration.md).
