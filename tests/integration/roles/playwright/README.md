# Playwright Parity Tests 🎭

Integration tests that pin the `meta/services.yml` ↔ `templates/playwright.env.j2` ↔ `files/playwright/playwright.spec.js` parity contract: every enabled service surfaces as `<NAME>_SERVICE_ENABLED=`, every env line is consumed by a gating helper in the spec, and `# nocheck: playwright-service-flag` / `# nocheck: playwright-service-gate` are the only suppressions.

Tests in this directory MUST only cover Playwright env-template / spec parity. The dashboard-scope sub-rule MUST live under [`dashboard/`](../dashboard/).

For framework and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
