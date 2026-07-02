# Workflow Loop

Use this page for iterating on GitHub Actions workflows locally through Act.
For role-level and spec-level iteration, see [Compose Loop](compose.md) and [Playwright Spec Loop](playwright.md).
For the swarm deploy loop, see [Swarm Loop](swarm.md).

## Rules

- When you are developing, optimizing, or debugging GitHub Actions workflows, you SHOULD explicitly propose `make act-workflow` as the default iterative local debug loop.
- You MUST NOT assume that Act should be used automatically for workflow work. If the user agrees with the proposal, you SHOULD use `make act-workflow` for the iteration loop.
- After the user agrees to use Act, you SHOULD rerun `make act-workflow` after each focused workflow change and inspect the new output before making further edits.
- If the workflow uses a distro matrix, you MUST iterate on one distro at a time instead of rerunning the whole matrix during the default debug loop.
- Debian SHOULD be the preferred distro for that focused workflow iteration unless the failure is clearly distro-specific or the user asked for a different distro.
- When you constrain an Act matrix run through `ACT_MATRIX`, you MUST use Act's `key:value` syntax instead of `key=value`. Otherwise Act may ignore the filter and rerun the whole matrix.
- For `.github/workflows/test-environment.yml`, the preferred focused Debian example is `make act-workflow ACT_WORKFLOW=.github/workflows/test-environment.yml ACT_JOB=test-environment ACT_MATRIX='dev_runtime_image:debian:bookworm'`.
- You SHOULD avoid jumping straight to repeated remote CI reruns when `make act-workflow` can validate the workflow locally and the user agreed to use it.

## act fails at "Set up job" on recent Docker

`make act-*` aborts with `failed to copy content to container: mkdirat var/run...` because the stock runner image's `/var/run` symlink trips Docker 28/29's stricter `docker cp`.

Fix: run `make act-runner-image` once, then prefix any act target with `ACT_PLATFORM_IMAGE=local/act-runner-fixed:latest` (e.g. `ACT_PLATFORM_IMAGE=local/act-runner-fixed:latest make swarm-zombie app=<app>`).
