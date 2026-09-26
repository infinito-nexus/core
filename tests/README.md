# Tests 🧪

All automated tests for Infinito.Nexus live here.

| Directory | Type | Guide |
|---|---|---|
| [`unit/`](unit/) | Unit tests (isolated, no I/O) | [unit.md](../docs/contributing/actions/testing/unit.md) |
| [`integration/`](integration/) | Integration tests (real component boundaries) | [integration.md](../docs/contributing/actions/testing/integration.md) |
| [`external/`](external/) | Opt-in live third-party checks, excluded from `make test` | [external.md](../docs/contributing/actions/testing/external.md) |
| [`e2e/`](e2e/) | End-to-end Playwright tests | [playwright.md](../docs/contributing/actions/testing/playwright.md) |
| [`regression/`](regression/) | Regression guard rules | [regression.md](../docs/contributing/actions/testing/regression.md) |
| [`lint/`](lint/) | Structural lint checks | [lint.md](../docs/contributing/actions/testing/lint.md) |

Run each suite via the `make` targets documented in the linked guides.
