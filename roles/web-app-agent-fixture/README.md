# Agent Fixture

## Description

Agent Fixture is a deliberately vulnerable web application. It is a static
front end served by nginx that carries seeded security and legal weaknesses on
purpose, so the Infinito.Nexus platform security agents have a known detection
target. It is not a real product and has no upstream homepage.

## Overview

This role deploys the fixture with Docker Compose behind the standard front
proxy, building a small custom nginx image from the tree under `files/app`.
The role refuses to run unless the inventory sets `AGENT_FIXTURE_BUNDLE: true`;
only the agents test bundle (`inventories/bundles/servers/agents`) sets that
flag, so the fixture never comes up on a real host and any other inventory
fails hard at the first task.

## Features

- **Bundle-guarded:** The first task asserts `AGENT_FIXTURE_BUNDLE` and aborts
  the deploy anywhere outside the agents test bundle.
- **Seeded instance findings:** A third-party web font from `fonts.googleapis.com`
  in `files/app/html/index.html`, a session cookie set before consent and a
  missing `X-Content-Type-Options` header in `files/app/config/nginx.conf`.
- **Seeded login throttle:** A `limit_req` throttle in front of `/login`, paired
  with the weak test credential and lockout policy in
  `files/app/fixtures/seeded-credentials.yml`, so credential brute forcing stays
  bounded.
- **Seeded static weaknesses:** A known-vulnerable dependency (`lodash` 4.17.11)
  in `files/app/package.json`, and a weak TLS profile in
  `files/app/config/tls-profile.conf`.
- **Seeded legal findings:** An AGPL-3.0 runtime dependency, an Apache-2.0
  dependency without its NOTICE, a build-only GPL-3.0 dependency, a vendored
  script without a licence (`files/app/html/static/thirdparty/confetti.js`), and
  a third-party brand logo used as the site's own branding
  (`files/app/html/static/thirdparty/northwind-logo.svg`).

## Use Cases

- Exercising the hacker agent's dependency, header, TLS and brute-force checks.
- Exercising the counsel agent's instance privacy probe and repository licence
  review against a target with known findings.

The credentials, hostnames and dependencies here are fixtures, not real
accounts or endpoints.
