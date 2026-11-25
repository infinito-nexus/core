# Deploy Job Entry

This directory holds the job entry that every CI deploy step and every job of the local runner pool of [svc-runner](../../../../roles/svc-runner/README.md#local-flavor) calls.

For the CI deploy flows it starts, see [../ci/README.md](../ci/README.md); for the local ones, see [../local/README.md](../local/README.md).

## Entry Points

| Script | What it does | Notes |
|---|---|---|
| `entry.sh <command> [args...]` | Changes into its checkout, prints the start line `[job-entry] start: <command> (checkout <path>)` and replaces itself with the deploy command, so the command's exit status is the job's. | Exports `INFINITO_DEPLOY_VIA_POOL=false`, so a job never submits itself to the pool again. [test_ci_deploy_through_entry.py](../../../../tests/lint/repository/test_ci_deploy_through_entry.py) fails on a workflow deploy step that bypasses it. |
