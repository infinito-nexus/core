# End-to-End CLI Tests

## Description

End-to-end CLI testing runs a role's own shell-based test harness against real, running containers
rather than a browser. It is the command-line counterpart to browser end-to-end testing: a harness
script brings up the infrastructure it needs (e.g. Docker-in-Docker peers), exercises it, and exits
non-zero on failure.

## Overview

This role discovers every role that ships a `tests/e2e.sh` harness, renders that role's optional
`tests/test.env.j2` into an env file, and runs each harness inside the deploy container (which holds
the host Docker socket, so the harness can spawn sibling containers — Docker-in-Docker). It mirrors the
discovery model of `test-e2e-playwright` but for CLI/shell suites, and is invoked post-deploy from the
constructor stage. Any role failure is collected and surfaced as a single failure at the end.

## Features

- **Automatic discovery:** Finds every `roles/<role>/tests/e2e.sh` marker, no per-role wiring needed.
- **Env contract:** Renders the role's `tests/test.env.j2` (with the role's own vars in scope) and
  sources it before running the harness.
- **Docker-in-Docker:** Runs in the deploy container with the host Docker socket, so harnesses can spin
  up sibling containers.
- **Scoping:** `TEST_E2E_CLI_ONLY_ROLES` / `TEST_E2E_CLI_SKIP_ROLES` restrict which roles run (default:
  the deployed app set).
- **Fail-aggregation:** Collects per-role failures and fails once at the end with the offending roles.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
