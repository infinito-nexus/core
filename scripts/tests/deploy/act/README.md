# Act Deploy Scripts

This directory holds the executable act deploy flows under `scripts/tests/deploy/act/`.

For local deploy flows, use [../local/README.md](../local/README.md).
For the canonical Make target index that invokes these helpers, see [make.md](../../../../docs/contributing/tools/make.md).

## Entry Points

| Command | What it does | Notes |
|---|---|---|
| `all.sh` | Runs `test-deploy-local.yml` across all selected distros. | Uses a linear matrix and passes the selected distro list through `INFINITO_DISTROS`. |
| `app.sh` | Runs `test-deploy-local.yml` for one app. | Uses `whitelist` to limit the workflow to the selected app. |
| `workflow.sh` | Runs any workflow file through `act`. | Supports custom job, matrix, container, network, and image settings. |
