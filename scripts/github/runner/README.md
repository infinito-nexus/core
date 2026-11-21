# Runner Hygiene 🧹

Shell helpers that prepare and inspect the GitHub-hosted runner host around image-build and deploy steps.

## Scope 📋

This directory contains host-level helpers: disk-space reclamation and reporting, a free-space guard that stops a step before the runner's root disk fills, swap-file enlargement, Docker-daemon cleanup, post-failure diagnostic dumps, and the build of the deploy image a job starts from its own checkout. Helpers MUST be invoked from workflow `run:` blocks under [`.github/workflows/`](../../../.github/workflows/) and MUST NOT be called from application code, Ansible roles, or any runtime path outside CI. They assume a GitHub-hosted Ubuntu runner and modify host-kernel state (mount points, swap, Docker storage) that does not exist inside the `infinito` container.

For the rationale behind disk reclamation and swap enlargement in deploy workflows see the "Disk space" and "Swap" sections in [workflow.md](../../../docs/contributing/artefact/files/github/workflow.md). For the workflow catalog that drives these calls see [workflows.md](../../../docs/contributing/tools/github/actions/workflows.md).
