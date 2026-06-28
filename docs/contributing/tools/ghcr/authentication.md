# GHCR Authentication 🔑

This guide explains how GitHub Container Registry (GHCR) authentication works for mirroring images via GitHub Actions.

## How Authentication Works 🔑

All workflows use `secrets.GITHUB_TOKEN` to log in to GHCR:

```yaml
- name: Login to GHCR
  uses: docker/login-action@...
  with:
    registry: ghcr.io
    username: ${{ github.actor }}
    password: ${{ secrets.GITHUB_TOKEN }}
```

No personal access token (PAT) or additional secrets are required.

## Why GITHUB_TOKEN Is the Correct Choice ✅

When a workflow runs in a public repository and pushes to GHCR using `GITHUB_TOKEN`, GitHub automatically:

1. Links the package to the repository.
2. Sets the package visibility to match the repository visibility (public → public).

This means mirrored images are published as public packages without any additional configuration.

## Docker Hub Rate Limits 🐳

To avoid Docker Hub pull rate limits when mirroring images, configure the following optional secrets:

| Name | Type | Description |
|---|---|---|
| `DOCKERHUB_USERNAME` | Secret | Docker Hub username |
| `DOCKERHUB_TOKEN` | Secret | Docker Hub access token |

These are used only for pulling source images from Docker Hub and are not required for GHCR authentication.

## Fork Pull Requests 🍴

Secrets are NOT available in `pull_request` workflows triggered by forks. This is a GitHub security restriction. The mirror and image build run via `pull_request_target` instead:

- A fork PR triggers a `pull_request_target` run that builds and mirrors any new images needed by the fork, authenticating to GHCR with the per-job `GITHUB_TOKEN`.
- The `pull_request` orchestrator then waits for and consumes those images.
- Untrusted fork builds run **without** organization secrets (`secrets: inherit` is not passed); Docker Hub mirror credentials are passed only for maintainer-trusted PRs (the `🛡️ Trusted` label). See [pipeline.md](../../artefact/git/pipeline.md#fork-prs-).

## Troubleshooting 🔧

If a push to GHCR fails with `denied: denied`:

1. Verify the workflow has `packages: write` in its `permissions` block.
2. Confirm the repository is public (private repositories require additional package visibility configuration).
3. Re-run the workflow after any permission or visibility changes.
