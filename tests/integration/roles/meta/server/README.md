# `server` Block Tests 🛡️

Integration tests that enforce invariants of the `server:` block in `roles/*/meta/services.yml`: Content-Security-Policy structure (whitelist / flags / hashes), supported directives, valid URL / Jinja / wildcard entries.

Tests in this directory MUST only cover the `server.*` sub-tree of `meta/services.yml`. Other top-level invariants live in the sibling [`services/`](../services/) cluster.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../../docs/contributing/actions/testing/integration.md).
