# Test: E2E Playwright Runner

## Description

This Ansible role provides a generic, reusable Playwright end-to-end (E2E) test runner
for the Infinito.Nexus ecosystem.

It automatically discovers roles that ship a Playwright test project under:

- `roles/<application_id>/templates/playwright.env.j2`
- `roles/<application_id>/files/playwright/playwright.spec.js`

A role is considered Playwright-enabled if it provides:

- `roles/<application_id>/templates/playwright.env.j2`

The role then stages the Playwright project to a local staging directory, renders a `.env`
file from `templates/playwright.env.j2`, optionally waits until the application is reachable, and executes
Playwright inside a Docker image derived from the central Playwright package version.

## Overview

This role:

- Discovers Playwright-enabled roles by scanning `roles/*/templates/playwright.env.j2`
- Supports allow-/deny-lists via `TEST_E2E_PLAYWRIGHT_ONLY_ROLES` and `TEST_E2E_PLAYWRIGHT_SKIP_ROLES`
- Stages each Playwright project into `TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR/<application_id>`
- Renders the central `package.json` template into each staged project and injects the central `playwright.config.js`
- Copies role-specific `files/playwright/playwright.spec.js` into the staged `tests/playwright.spec.js`
- Renders `.env` from `templates/playwright.env.j2` using Ansible variables (`application_id`, `domains`, `users`, `applications`)
- Optionally waits until the application responds with HTTP `200` or `302`
- Injects CA trust automatically for `TLS_MODE=self_signed` (via `CA_TRUST.*`), so Playwright accepts self-signed cert chains
- Runs Playwright in Docker with stable browser settings (`--ipc=host`, `--shm-size=1g`)
- Stores per-role reports/artifacts under `TEST_E2E_PLAYWRIGHT_REPORTS_BASE_DIR/<application_id>`

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## Purpose

The purpose of this role is to provide a central E2E test primitive that can be executed
at the end of a deployment (for example, as a post task), without hardcoding tests in the
runner itself.

Each application role stays responsible for its own Playwright tests and configuration.
This role only provides the execution framework.

## Role contract (what application roles must provide)

A Playwright-enabled role must provide:

```
roles/<application_id>/
    templates/playwright.env.j2
    files/playwright/playwright.spec.js
```

For the file-level contract, use [Contributing `playwright.env.j2`](../../docs/agents/files/role/playwright.env.j2.md) and [Contributing `playwright.spec.js`](../../docs/contributing/artefact/files/role/playwright.specs.js.md).

`package.json` and `playwright.config.js` are provided centrally by this role:

- `roles/test-e2e-playwright/templates/package.json.j2` (rendered per-deploy; pins `@playwright/test` from `meta/services.yml.playwright.version`)
- `roles/test-e2e-playwright/files/playwright.config.js` (copied as-is)

## Included files

This role ships central Playwright defaults:

- `templates/package.json.j2`: `@playwright/test` version derived from `meta/services.yml.playwright.version`
- `files/playwright.config.js`: shared Playwright configuration

Both are used as central defaults for every app role.

## Variables

### Staging & reports

- `TEST_E2E_PLAYWRIGHT_STAGE_BASE_DIR` (default: `/tmp/test-e2e-playwright`)
- `TEST_E2E_PLAYWRIGHT_REPORTS_BASE_DIR` (default: `/var/lib/infinito/logs/test-e2e-playwright`)

### Playwright runtime

- `TEST_E2E_PLAYWRIGHT_IMAGE` (resolved in `vars/main.yml` from `meta/services.yml.playwright.image` + `.version` via `lookup('config', 'test-e2e-playwright', 'services.playwright.image|version')`)
- `TEST_E2E_PLAYWRIGHT_IMAGE_DISTRO` (default: `noble`)
- `TEST_E2E_PLAYWRIGHT_COMMAND` (default: `npm install --no-fund --no-audit && npx playwright test`)

### Readiness wait

- `TEST_E2E_PLAYWRIGHT_WAIT_ENABLED` (default: `true`)
- `TEST_E2E_PLAYWRIGHT_WAIT_RETRIES` (default: `30`)
- `TEST_E2E_PLAYWRIGHT_WAIT_DELAY` (default: `5`)

### Discovery filters

- `TEST_E2E_PLAYWRIGHT_ONLY_ROLES` (default: `allowed_applications`)
- `TEST_E2E_PLAYWRIGHT_SKIP_ROLES` (default: `[]`)

## Design notes

- The runner is intentionally test-agnostic at runtime: it executes only tests provided by application roles.
- `playwright.version` in `meta/services.yml` is the single source of truth for the default Playwright version; the central `templates/package.json.j2` pins it via the `image_version` filter.
- `templates/playwright.env.j2` acts as the stable marker for discovery and as the source of environment configuration.
- Playwright is executed in Docker for reproducibility and consistent browser dependencies.
- In `TLS_MODE=self_signed`, the role requires `CA_TRUST.cert_host`, `CA_TRUST.wrapper_host`, and `CA_TRUST.trust_name` and fails early if cert/wrapper files are missing.

## How to use

1. Add the two app-specific files:
   - `roles/<application_id>/templates/playwright.env.j2`
   - `roles/<application_id>/files/playwright/playwright.spec.js`
   Follow [Contributing `playwright.env.j2`](../../docs/agents/files/role/playwright.env.j2.md) and [Contributing `playwright.spec.js`](../../docs/contributing/artefact/files/role/playwright.specs.js.md) while creating them.
2. Run deployment and include your app in `allowed_applications` (or leave it empty to run all discovered apps).
3. Keep `package.json` and `playwright.config.js` centralized in `roles/test-e2e-playwright/` (`templates/package.json.j2` and `files/playwright.config.js`).

Example override for running only one spec:

`-e TEST_E2E_PLAYWRIGHT_COMMAND='npm install --no-fund --no-audit && npx playwright test tests/login.spec.js'`

## Recording

For interactive Playwright recording, use the external repository:

[playwright-recorder](https://github.com/kevinveenbirkenbach/playwright-recorder)

This role no longer ships its own local recording wrapper.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
