# Dashboard Integration Scope Tests 🎛️

Integration tests that enforce the dashboard-tile scope rule: only `web-app-*` roles may declare `dashboard.{enabled,shared}` truthy; non-`web-app-*` roles MUST drop the entry or ship a static `dashboard: { enabled: false, shared: false }`.

Tests in this directory MUST only cover the dashboard-scope contract. Playwright env-template / spec parity tests MUST live under [`playwright/`](../playwright/).

For framework and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
