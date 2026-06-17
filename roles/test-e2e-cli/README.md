# End-to-End CLI Tests

## Description

End-to-end CLI testing exercises a role's own shell-based test harness against real, running
containers instead of a browser. It is the command-line counterpart to browser end-to-end testing:
a harness script brings up whatever it needs (for example Docker-in-Docker peers), drives it, and
exits non-zero on failure.

## Overview

This role discovers every role that ships a `templates/test.env.j2`, renders that env, and runs the
role's `files/test/test.sh` inside the deploy container (which holds the host Docker socket, so the
harness can spawn sibling containers). It mirrors the discovery model of `test-e2e-playwright` for
CLI/shell suites and is invoked post-deploy from the server, universal and workstation stages. Per-role
failures are collected and surfaced as a single failure at the end.

## Features

- **Automatic discovery:** Finds every role with a `templates/test.env.j2` marker, no per-role wiring.
- **Env contract:** Renders the role's `templates/test.env.j2` (with the role's own vars in scope) and
  sources it before running the harness.
- **Docker-in-Docker:** Runs in the deploy container with the host Docker socket, so harnesses can
  spin up sibling containers.
- **Scoping:** `TEST_E2E_CLI_ONLY_ROLES` / `TEST_E2E_CLI_SKIP_ROLES` restrict which roles run; discovery
  is already limited to roles deployed on the host.
- **Fail aggregation:** Collects per-role failures and fails once at the end with the offending roles.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
