# Environment Test Suite

This directory contains the modular environment test suite for Infinito.Nexus.
It validates the full local development flow from a clean state.

The entry point is [00_orchestrator.sh](00_orchestrator.sh).

## Structure

| File | Purpose |
|---|---|
| [00_orchestrator.sh](00_orchestrator.sh) | Runs all numbered steps in order |
| [01_install.sh](01_install.sh) | Installs package prerequisites and repository dependencies |
| [02_system.sh](02_system.sh) | Shows disk usage and purges cached state |
| [03_build.sh](03_build.sh) | Builds the local Docker image |
| [04_bootstrap.sh](04_bootstrap.sh) | Bootstraps the development environment and starts the stack |
| [05_commit.sh](05_commit.sh) | Validates pre-commit hook enforcement and `--no-verify` bypass |
| [06_test.sh](06_test.sh) | Runs the full validation suite |
| [07_compose_minimal.sh](07_compose_minimal.sh) | Compose deploy on minimal hardware with service exclusion |
| [08_compose_performance.sh](08_compose_performance.sh) | Compose deploy of the full application set on performance hardware |
| [09_compose_reuse.sh](09_compose_reuse.sh) | Compose redeploy reusing existing inventory and packages |
| [10_teardown.sh](10_teardown.sh) | Shuts down the stack and reverses environment changes |
| [11_console.sh](11_console.sh) | Smoke-tests the interactive console REPL |
| [12_swarm.sh](12_swarm.sh) | Swarm deploy of the MariaDB database role (svc-db-mariadb) |
| [13_roundtrip.sh](13_roundtrip.sh) | Compose+swarm roundtrip of the PostgreSQL database role (svc-db-postgres) |
| [utils/common.sh](utils/common.sh) | Shared bootstrap, constants, and generic helpers (HTTP assertion, inventory inspection) |
| [utils/cache.sh](utils/cache.sh) | Cache-stack assertions and probes (registry-cache, package-cache, DiD inner-build) |

## Usage

Run the full suite via the entry point:

```bash
bash scripts/tests/environment/00_orchestrator.sh
```

For documentation on the overall development workflow, see the [Deploy Guide](../../../docs/administration/deploy.md).
