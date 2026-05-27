# Prometheus Service Tests 📈

Integration tests that enforce invariants of the prometheus integration: every web-app/svc role declares the shared `prometheus` service entry, the prometheus role's own nginx + docker-health wiring is intact, and the native-metrics scrape contract (`services.prometheus.native_metrics.enabled` ⇔ `templates/prometheus.yml.j2`) holds across the roles tree.

Tests in this directory MUST only cover prometheus-specific wiring and the prometheus service entry. Broader `meta/services.yml` shape rules MUST live one level up in [`services/`](../); the ordering-only `galaxy_info.run_after` cluster lives in [`run_after/`](../run_after/).

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../../../docs/contributing/actions/testing/integration.md).
