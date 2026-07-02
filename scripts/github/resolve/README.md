# Workflow Input Resolution 🔎

Shell helpers that derive structured inputs and outputs for GitHub Actions jobs from repository state.

## Scope 📋

This directory contains pure resolvers that read repository state (git history, role metadata, version tags, input environment variables) and emit resolved values either via `$GITHUB_OUTPUT` or stdout. Resolvers MUST be idempotent and MUST NOT mutate repository or registry state beyond writing to `$GITHUB_OUTPUT`. The covered concerns are distro selection for push CI, diff-driven app whitelist resolution, the `🧩 Subset` label dispatch (`pr_affected_roles.sh`, which picks between the PR-body subset and the diff resolver), release-tag parsing, app discovery for the deploy matrix, and change detection that gates the update pipeline.

For the workflow catalog that consumes these outputs see [workflows.md](../../../docs/contributing/tools/github/actions/workflows.md). For the diff-driven whitelist contract see the "Diff-driven app selection" section in [pipeline.md](../../../docs/contributing/artefact/git/pipeline.md).
