# Workspace Test Suite

This directory contains the modular workspace test suite for Infinito.Nexus.
It validates the full local development flow from a clean state.

The entry point is [00_orchestrator.sh](00_orchestrator.sh). It runs one or more
*tracks* — subdirectories whose numbered scripts execute in order.

## Tracks

`base` prepares the workspace and is a prerequisite for the other two. `compose`
and `swarm` are independent of each other, which is what lets CI run them as
separate jobs with a budget each.

| Track | File | Purpose |
|---|---|---|
| base | [base/01_install.sh](base/01_install.sh) | Installs package prerequisites and repository dependencies |
| base | [base/02_system.sh](base/02_system.sh) | Shows disk usage and purges cached state |
| base | [base/03_build.sh](base/03_build.sh) | Builds the local Docker image |
| base | [base/04_bootstrap.sh](base/04_bootstrap.sh) | Bootstraps the development environment and starts the stack |
| base | [base/05_commit.sh](base/05_commit.sh) | Validates pre-commit hook enforcement and `--no-verify` bypass |
| base | [base/06_test.sh](base/06_test.sh) | Runs the full validation suite |
| base | [base/07_console.sh](base/07_console.sh) | Smoke-tests the interactive console REPL |
| compose | [compose/01_minimal.sh](compose/01_minimal.sh) | Compose deploy on minimal hardware with service exclusion |
| compose | [compose/02_performance.sh](compose/02_performance.sh) | Compose deploy of the full application set on performance hardware |
| compose | [compose/03_reuse.sh](compose/03_reuse.sh) | Compose redeploy reusing existing inventory and packages |
| compose | [compose/04_teardown.sh](compose/04_teardown.sh) | Shuts down the stack and reverses environment changes |
| swarm | [swarm/01_teardown.sh](swarm/01_teardown.sh) | Releases the development stack so the swarm cluster runs alone |
| swarm | [swarm/02_zombie.sh](swarm/02_zombie.sh) | Swarm deploy of the MariaDB database role (svc-db-mariadb) |
| swarm | [swarm/03_roundtrip.sh](swarm/03_roundtrip.sh) | Compose+swarm roundtrip of the PostgreSQL database role (svc-db-postgres) |
| swarm | [swarm/04_teardown.sh](swarm/04_teardown.sh) | Shuts down the stack and reverses environment changes |

| Shared | Purpose |
|---|---|
| [utils/common.sh](utils/common.sh) | Shared bootstrap, constants, and generic helpers (HTTP assertion, inventory inspection) |
| [utils/cache.sh](utils/cache.sh) | Cache-stack assertions and probes (registry-cache, package-cache, DiD inner-build) |
| [utils/teardown.sh](utils/teardown.sh) | Stack shutdown and environment reversal, shared by both closing steps |

## Usage

Run every track via the entry point:

```bash
bash scripts/tests/workspace/00_orchestrator.sh
```

Run selected tracks, in the order given, through `INFINITO_WORKSPACE_TRACKS`:

```bash
INFINITO_WORKSPACE_TRACKS="base swarm" bash scripts/tests/workspace/00_orchestrator.sh
```

An unknown track name aborts before anything else runs.

For documentation on the overall development workflow, see the [Deploy Guide](../../../docs/administration/deploy.md).
