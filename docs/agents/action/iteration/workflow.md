# Workflow Loop

Use this page for iterating on GitHub Actions workflows locally through Act.
For role-level and spec-level iteration, see [Role Loop](role.md) and [Playwright Spec Loop](playwright.md).

## Rules

- When you are developing, optimizing, or debugging GitHub Actions workflows, you SHOULD explicitly propose `make act-workflow` as the default iterative local debug loop.
- You MUST NOT assume that Act should be used automatically for workflow work. If the user agrees with the proposal, you SHOULD use `make act-workflow` for the iteration loop.
- After the user agrees to use Act, you SHOULD rerun `make act-workflow` after each focused workflow change and inspect the new output before making further edits.
- If the workflow uses a distro matrix, you MUST iterate on one distro at a time instead of rerunning the whole matrix during the default debug loop.
- Debian SHOULD be the preferred distro for that focused workflow iteration unless the failure is clearly distro-specific or the user asked for a different distro.
- When you constrain an Act matrix run through `ACT_MATRIX`, you MUST use Act's `key:value` syntax instead of `key=value`. Otherwise Act may ignore the filter and rerun the whole matrix.
- For `.github/workflows/test-environment.yml`, the preferred focused Debian example is `make act-workflow ACT_WORKFLOW=.github/workflows/test-environment.yml ACT_JOB=test-environment ACT_MATRIX='dev_runtime_image:debian:bookworm'`.
- You SHOULD avoid jumping straight to repeated remote CI reruns when `make act-workflow` can validate the workflow locally and the user agreed to use it.
- You MAY widen the scope to `make act-app` or `make act-all` when the problem spans more than one workflow or `make act-workflow` is too narrow for the failure.

## Inspect before redeploy

A swarm `act-swarm-zombie` run rebuilds a full DinD cluster over tens of minutes, so a wrong fix wastes a whole rebuild. Confirm fixes on live state first.

- The run leaves the cluster up (`INFINITO_KEEP_SWARM_NODES=true`). Before redeploying, reproduce the failure and confirm the candidate fix on it via `make act-swarm-exec` / `make act-swarm-shell` (chmod the file, re-render the artifact, re-run the failing command); release with `make act-swarm-down`.
- You MAY confirm an early-stage fix (config render, realm import) on the live cluster while the run is still going; no need to wait for it to finish.
- In-cluster edits are validation only; the repo change is the real fix. Validate before redeploying, since the redeploy tears the cluster down.
- Do NOT commit during an active iteration. Commit only after it reaches green: a mid-iteration commit is unverified, and committing while a deploy is live makes the pre-commit hook stash the working-tree files the deploy is reading and corrupts the run.
- If a commit is genuinely unavoidable mid-iteration, use `--no-verify` (it skips the stashing hook). `make autoformat` and `make test` are safe to run at any time (they do not stash).
- Exception: failures the current cluster cannot show (pre-cluster steps like app discovery, render-time lookup errors, multi-node placement). Say so instead of faking an in-cluster check.

## act fails at "Set up job" on recent Docker

`make act-*` aborts with `failed to copy content to container: mkdirat var/run...` because the stock runner image's `/var/run` symlink trips Docker 28/29's stricter `docker cp`.

Fix: run `make act-runner-image` once, then prefix any act target with `ACT_PLATFORM_IMAGE=local/act-runner-fixed:latest` (e.g. `ACT_PLATFORM_IMAGE=local/act-runner-fixed:latest make act-swarm-zombie app=<app>`).
