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
| `once` | `true` runs the test in the sync pass only, so `full_cycle` does not run it a second time |

```yaml
cli:
  once: true
  timeout: 14400
```
