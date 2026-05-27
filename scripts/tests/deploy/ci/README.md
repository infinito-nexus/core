# CI Deploy Scripts

This directory holds the executable CI deploy flows under `scripts/tests/deploy/ci/`.

For local deploy flows, use [../local/README.md](../local/README.md).

## Entry Points

| Script | What it does | Notes |
|---|---|---|
| `all.sh` | Runs one app across all selected distros, serially. | Uses `dedicated.sh` for the per-distro deploy loop. |
| `dedicated.sh` | Deploys one app on one distro twice against the same stack. | Performs the full CI cleanup after the run. |
