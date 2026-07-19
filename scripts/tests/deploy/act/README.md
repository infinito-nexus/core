# Act Deploy Scripts

This directory holds the executable act deploy flows under `scripts/tests/deploy/act/`.

For local deploy flows, use [../local/README.md](../local/README.md).
For the canonical Make target index that invokes these helpers, see [make.md](../../../../docs/contributing/tools/make.md).

## Entry Points

| Command | What it does | Notes |
|---|---|---|
| `workflow.sh` | Runs any workflow file through `act`. | Supports custom job, matrix, container, network, and image settings. Invoked via `make act-workflow ACT_WORKFLOW=<file>`. |
