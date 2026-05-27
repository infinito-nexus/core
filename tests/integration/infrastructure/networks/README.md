# Network Tests 🕸️

Integration tests that enforce the contract between `group_vars/all/08_networks.yml` and the roles that require a container network: subnets MUST be valid, unique, and non-overlapping, network names MUST map to an `application_id`, and every role that ships a `compose.yml.j2` with an `application_id` MUST have a network entry under `defaults_networks.local`.

Tests in this directory MUST only cover `08_networks.yml` consistency and its coupling to roles. Tests for port allocations MUST live under `tests/integration/ports/`, and domain-related checks MUST live under `tests/integration/domains/`.

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
