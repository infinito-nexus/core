# Network & Domain Lint 🌐

Network-literal hygiene: ban on hardcoded DNS resolver IPs outside `NETWORK_PUBLIC_DNS_RESOLVERS`, and on `<word>.{{ DOMAIN_PRIMARY }}` host literals outside the meta SPOT.

Tests in this directory MUST only cover network/DNS/domain literal patterns. Compose- and role-level network structure MUST live under `tests/integration/infrastructure/networks/`.

For framework and `make test-lint` usage see [lint.md](../../../../docs/contributing/actions/testing/lint.md).
