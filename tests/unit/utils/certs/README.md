# Certificate & TLS Unit Tests 🔐

Unit tests for the top-level certificate and TLS helper modules in [`utils/`](../../../../utils/): `cert_utils.py` (wildcard/exact match logic, newest-certificate selection) and `tls_common.py` (flavor handling, SAN overrides, domain normalisation).

Tests in this directory MUST only cover the pure-function behaviour of `utils.cert_utils` and `utils.tls_common`. Lookup-plugin integration that depends on these modules MUST live under [`tests/unit/plugins/lookup/`](../../plugins/lookup/).

For framework and `make test-unit` usage see [unit.md](../../../../docs/contributing/actions/testing/unit.md).
