# Test E2E Cli

## Description

[Test E2E Cli](https://example.com/) is an application.

## Overview

This role deploys Test E2E Cli.

## Features

- **Feature:** Describe a capability.

## Per-role settings

A tested role declares its CLI-test settings under `cli:` in its own `meta/tests.yml`, read through `lookup('role_tests', application_id, 'cli.<key>')`:

| Key | Purpose |
|---|---|
| `timeout` | Seconds for the test script, for a test that legitimately outlasts `TEST_E2E_CLI_TIMEOUT` |
| `container_service_key` | Service key whose container the test runs against |
| `once` | `true` runs the test in the first pass only, so the update pass of `full_cycle` does not run it a second time |

```yaml
cli:
  once: true
  timeout: 14400
```

The script runs with `CLI_DEADLINE` exported, the epoch second the harness kills it. A script that retries budgets against it, so it can still print its own verdict before the harness ends it.

## How often a test runs

A role's test runs once per CLI node, not once per play host. Without `container_service_key` every host is its own CLI node. With it, every host resolves the node that holds the service's container, so in swarm all hosts of the role share one node and one run. The stack host (`STACK_HOST`) runs it when it is one of them, else the first of them in play order, and `test.env` renders from that host's variables. Each host claims `<role>@<node>`, so a host that skips a role (a manager-only placement) keeps an older claim that never matches it. A failed run counts as a failure on every host that shares its node.
