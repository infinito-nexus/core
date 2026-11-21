# Runner Pool 🏃

Building blocks of the local runner pool, which runs every local deploy as a job of one of N runners. Nothing here starts a container or touches a cache.

## Modules 🧭

| Module | Purpose |
|---|---|
| [count.py](count.py) | The default pool size behind `make runner-count`: the minimum of RAM, CPU and disk divided by the per-deploy budgets, at least 1. The disk term subtracts the remaining cache growth, the sum of `max(0, cap - used)` over the rows `make cache-status` prints, and `INFINITO_CACHE_DISK_FLOOR` from the free disk. `INFINITO_RUNNER_COUNT` overrides the result. |
| [jobs.py](jobs.py) | The file-based job queue: submit, claim by one idle runner under a lock, the states `queued`, `running`, `held`, `done` and `failed`, hold and release, the queue position, the wait with an optional timeout that withdraws the job, the log follow that returns the job's exit status, and the cleanup report of held jobs and job stacks without a record. |
| [checkmk_local_check.py](checkmk_local_check.py) | The Checkmk local check lines: one service per runner, held job, cache and the disk floor. A held job warns from `INFINITO_HELD_JOB_WARN_AGE` (default `24h`) and is critical from `INFINITO_HELD_JOB_CRIT_AGE` (default `7d`); a cache above its cap and free disk below the floor are critical. |

## Calibration 📐

The per-deploy budgets come from `inventories/development/runner-calibration.yml`, which records the measured full deploy they come from:

```yaml
applications: [web-app-dashboard, web-app-keycloak]
commit: dde9318aac
date: 2026-11-07
peak_memory: 8g
cpus: 4
disk_growth: 20g
```

The values above only show the shape. Until a measured deploy is recorded, `make runner-count` refuses unless `INFINITO_RUNNER_COUNT` sets the count, and [test_runner_calibration.py](../../tests/lint/repository/test_runner_calibration.py) fails on a budget without its record.
