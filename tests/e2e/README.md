# End-to-End Tests 🎭

Playwright is the E2E framework for all `web-*` roles.
Tests are role-local. Each role ships its own `files/playwright/playwright.spec.js` and `templates/playwright.env.j2`
and is discovered automatically by the shared `test-e2e-playwright` runner.

See [playwright.md](../../docs/contributing/actions/testing/playwright.md) for the SPOT: runner integration, file contracts, recording tools, and development procedure.
