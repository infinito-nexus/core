# Continuous Integration 🔄

This document describes the CI pipeline structure, entry points, and gates used in Infinito.Nexus. For the catalog of every workflow file (description, triggers, inputs) see [workflows.md](../../tools/github/actions/workflows.md).

## Overview 🗺️

CI is triggered automatically on pull-request events and on pushes to the branches listed in the entry-workflow row in [workflows.md](../../tools/github/actions/workflows.md). The pipeline is composed of reusable workflow files under [.github/workflows/](../../../../.github/workflows/). The central coordinator is [ci-orchestrator.yml](../../../../.github/workflows/ci-orchestrator.yml), which is called by the entry workflows.

## Entry Points 🚪

Every external CI trigger MUST route through one of the entry workflows. Each entry translates its event into a call to the orchestrator; the catalog of triggers and inputs lives in [workflows.md](../../tools/github/actions/workflows.md).

- [entry-pull-request-change.yml](../../../../.github/workflows/entry-pull-request-change.yml): detects PR scope and conditionally calls the orchestrator.
- [entry-push-latest.yml](../../../../.github/workflows/entry-push-latest.yml): calls the orchestrator for pushes on the supported branch prefixes and additionally invokes the release workflow on version tags. For the contributor-facing release procedure see [release.md](../../actions/release.md).
- [entry-manual.yml](../../../../.github/workflows/entry-manual.yml): dispatches the orchestrator manually for a chosen distro set and whitelist.

The push entry synchronizes the current repository's `main` branch from the configured source repository before CI policy and deploy discovery run.
The default source is `infinito-nexus/core`, and `CI_SYNC_MAIN_SOURCE_REPOSITORY` MAY override or disable the sync as documented in [configuration.md](../../tools/github/actions/configuration.md).
This sync **force-overwrites** the local `main`, so on a synced repository you MUST NOT work directly in `main`; use a `feature/**`, `fix/**`, or `hotfix/**` branch and treat `main` as a read-only mirror.

## PR Scope Detection 🔎

Before the full pipeline runs, CI detects the scope of the PR based on the changed files and the branch prefix (see [branch.md](branch.md)).

- Documentation-only and agent-only PRs MUST pass a lightweight gate without running the full orchestrator.
- All other scopes MUST run the full [ci-orchestrator.yml](../../../../.github/workflows/ci-orchestrator.yml).
- The branch prefix MUST match the detected scope, otherwise the `validate-pr-branch-prefix` job fails.

## Pipeline Stages 🏗️

The orchestrator runs the following stages in order:

### 1. Fork Prerequisites ⏳

For fork PRs, CI waits for privileged images built by the `pull_request_target` event before proceeding. For an untrusted fork that build runs from the safe base merge ref **without organization secrets** (only the per-job `GITHUB_TOKEN`); a maintainer-applied `🛡️ Trusted` label switches the build source to the PR head, unlocks the mirror credentials, and skips the wait — see [Trusted fork PRs](#trusted-fork-prs-).

### 2. Security 🛡️

The `security-codeql` job runs the CodeQL scan (catalogued in the `Security and linting` table of [workflows.md](../../tools/github/actions/workflows.md)). A failing scan MUST fail `code-quality-gate` and thereby block all downstream deploy, install, and environment tests.

### 3. Linting 🧹

All linting workflows listed in the `Security and linting` table of [workflows.md](../../tools/github/actions/workflows.md) run in parallel. All of them MUST pass `lint-gate` before the pipeline continues.

### 4. CI Image Build 🐳

The `build-ci-images` stage uses [images-build-ci.yml](../../../../.github/workflows/images-build-ci.yml) to build Docker images for the target distributions (`arch`, `debian`, `ubuntu`, `fedora`, `centos`). These images are consumed by all subsequent test jobs.

### 5. Code Tests 🧪

All code-test workflows listed in the `Code tests` table of [workflows.md](../../tools/github/actions/workflows.md) run in parallel once the CI images are available. All of them MUST pass `test-code-gate`.

### 6. Code Quality Gate 🚦

The `code-quality-gate` requires linting, code tests, and security checks to all pass before deploy tests are triggered.

### 7. DNS Tests 🌐

[test-dns.yml](../../../../.github/workflows/test-dns.yml) validates DNS configuration across all target distributions.

### 8. Image Mirroring 🪞

[images-mirror-missing.yml](../../../../.github/workflows/images-mirror-missing.yml) mirrors any missing upstream images in parallel with the DNS tests so later deploy jobs pull from GHCR instead of Docker Hub, MCR, or other external registries. This shields CI from upstream rate limits, geo-blocking, and transient registry outages.

Fork PRs cannot publish mirror packages directly, so their runs wait for the `pull_request_target` mirror producer before continuing. The producer mirrors with the Docker Hub credentials only for trusted PRs ([🛡️ Trusted](#trusted-fork-prs-)); untrusted forks mirror anonymously (no organization secrets). See [mirror.md](../image/mirror.md) for the mirroring architecture and naming convention.

GHCR publication uses the workflow `GITHUB_TOKEN`; optional Docker Hub secrets are used only to reduce source-side Docker Hub rate limits while mirroring. See [authentication.md](../../tools/ghcr/authentication.md).

### 9. Deploy Tests 🚀

The three deploy-test workflows listed in the `Infrastructure tests` table of [workflows.md](../../tools/github/actions/workflows.md) (server, universal, workstation scopes) run in parallel once DNS and mirroring have completed.

#### Diff-driven app selection 🎯

Each of [test-deploy-server.yml](../../../../.github/workflows/test-deploy-server.yml), [test-deploy-universal.yml](../../../../.github/workflows/test-deploy-universal.yml), and [test-deploy-workstation.yml](../../../../.github/workflows/test-deploy-workstation.yml) narrows its app matrix to the set of roles actually impacted by the branch's diff against `origin/main`. The `discover` job resolves an effective whitelist before [output_apps.sh](../../../../scripts/github/resolve/output_apps.sh) runs, using the following precedence:

1. **Sentinel `__ALL__` in the `whitelist` input** (case-insensitive). The diff logic MUST be skipped and an empty whitelist MUST be emitted, which deploys everything in the workflow's scope. This is the explicit opt-out from diff narrowing for manual dispatch.
2. **Any other non-empty `whitelist`** (forwarded from `entry-manual.yml` and similar). The explicit value MUST win over the diff and is passed through verbatim.
3. **Diff vs `origin/main`**, applied only when the `whitelist` input is empty:
   - **No diff at all** OR **any changed path outside `roles/<role>/...`**: no whitelist is set, so the full deploy across the workflow's scope runs.
   - **All changed paths under `roles/<role>/...`**: the changed roles become the seed set, and the whitelist is the transitive closure of those seeds expanded upwards over `run_after`, `dependencies`, and shared services. In other words, every role whose prerequisite set as defined by [combined resolver](../../../../cli/meta/roles/applications/resolution/combined/resolver.py) contains one of the seeds is included, together with the seeds themselves.

The reverse closure is fail-safe: any seed that is not modellable in the resolver (no `application_id` and not referenced by any role's `run_after`) MUST trigger a fall-back to a full deploy, as MUST any resolver runtime error. The closure MUST NOT silently shrink the deploy matrix on partial information.

The PR-scope short-circuits in [scope.sh](../../../../scripts/meta/resolve/pr/scope.sh) (documentation-only, agent-only) still apply at the entry layer. They skip the orchestrator entirely and are independent of the diff-driven whitelist resolution above.

The reverse closure is implemented in [affected resolver](../../../../cli/meta/roles/applications/resolution/affected/__main__.py) and invoked from [affected_roles.sh](../../../../scripts/meta/resolve/diff/affected_roles.sh). The workflow glue lives in [effective_whitelist.sh](../../../../scripts/github/resolve/effective_whitelist.sh). [test-deploy-local.yml](../../../../.github/workflows/test-deploy-local.yml) MUST NOT apply this resolution. Local dispatch keeps the explicit whitelist semantics.

#### Subset label 🧩

Add a `## Roles` section with a fenced `roles:` YAML list to the PR body and apply the `🧩 Subset` label:

````markdown
## Roles

```yaml
roles:
  - web-app-nextcloud
  - web-app-matomo
  - sys-version
```
````

With the label set, the `detect-affected-roles` job in [entry-pull-request-change.yml](../../../../.github/workflows/entry-pull-request-change.yml) calls [pr_affected_roles.sh](../../../../scripts/github/resolve/pr_affected_roles.sh), which runs the [cli.meta.ci.subset_roles](../../../../cli/meta/ci/subset_roles.py) module. The module reads the first fenced block whose YAML carries a `roles:` key (the heading text is not matched) and emits that list as the `whitelist` output with `roles_only=true`, which flows into the deploy tests as precedence rung 2 above. Without the label, the diff-driven precedence applies.

The subset path fails the run when:

- the YAML is invalid,
- no `roles:` block is found,
- the `roles:` list is empty, or
- any listed id is not an existing `roles/<id>` directory.

The `🧩 Subset` label must exist in the repository's label set and is applied through the PR labels UI. Both the `pull_request` and `pull_request_target` events carry a `labeled` trigger, so adding it starts a fresh run.

### 10. Installation Tests 📦

The install-test workflows listed in the `Infrastructure tests` table of [workflows.md](../../tools/github/actions/workflows.md) run in parallel once `code-quality-gate` is green. All of them MUST pass `test-install-gate`.

### 11. Development Environment 🛠️

The `test-development` stage runs the development-environment workflow listed in the `Infrastructure tests` table of [workflows.md](../../tools/github/actions/workflows.md).

### 12. Done 🏁

The final `done` job aggregates all deploy, install, and development gates. CI is considered green only when this job succeeds.

## Concurrency 🔀

- PR pipelines use `cancel-in-progress: true` so only the newest run per PR and event type is active.
- The orchestrator uses `cancel-in-progress: false` to avoid interrupting long-running deploy tests mid-flight.
- The push entry workflow (`entry-push-latest.yml`) defaults to `cancel-in-progress: true` but respects the repository variable `CI_CANCEL_IN_PROGRESS`.

See [configuration.md](../../tools/github/actions/configuration.md) for all repository variables that control CI behaviour.

## Fork PRs 🍴

Fork PRs run under the `pull_request` event without write permissions. Privileged steps (image builds, package writes) run via `pull_request_target`. The fork CI waits for those privileged images before proceeding. See [pull-request.md](pull-request.md) for the contributor-facing fork workflow.

By default — for an **untrusted** fork PR — the privileged `pull_request_target` build checks out the **base merge ref** (`refs/pull/<N>/merge`) from the base repository: the PR's changes merged onto base, with all workflow and build-orchestration scripts coming from base, never from the fork. Because `actions/checkout` otherwise refuses to fetch a PR ref under `pull_request_target`, the source checkout sets `allow-unsafe-pr-checkout: true`. The untrusted build runs **without organization secrets** — `secrets: inherit` is not passed and it authenticates to GHCR with the per-job `GITHUB_TOKEN` only, so a malicious fork cannot read repository/organization secrets. (The `pull_request_target` token still carries `packages: write`, so the `🛡️ Trusted` label remains the real trust boundary for anything beyond image publication.)

### Trusted fork PRs 🔓

When a maintainer applies the `🛡️ Trusted` label, the fork PR is treated as deliberately released code:

- The orchestrator's `wait-fork-prereq-run` job **skips the wait** for the privileged fork images.
- The privileged `pull_request_target` build switches its **build source** from the base merge ref to the **raw PR head** (`head.repo.full_name` @ `head.sha`).
- The trusted build additionally receives the Docker Hub mirror credentials (passed only when the label is present); untrusted builds mirror anonymously.
- The built image **keeps the merge-SHA tag** (`ci-<merge_sha>`) so the `pull_request` orchestrator finds it unchanged — no consumer workflow has to know about the label.

Security gates:

- The `🛡️ Trusted` label flips the build source to the PR head and unlocks the Docker Hub credentials; without it the safe base merge ref is built with no organization secrets. Restrict who may set the label via repository label permissions / branch protection so only maintainers can grant it.
- Build-orchestration scripts (`scripts/image/push.sh` and the helper checkout) always come from the base repo at `github.sha`; only the Docker build **context** (`_src`) is the fork head. `persist-credentials: false` keeps the token out of the source checkout, and `USE_NIX_TOKEN` stays disabled for fork-sourced builds.
- Fork `pull_request` runs always receive a read-only token (GitHub-enforced); the label never grants write tokens or secrets to the untrusted event.

Both events carry a `labeled` trigger, so applying the `🛡️ Trusted` label starts fresh runs that already observe it: the `pull_request_target` build switches to the PR head and the `pull_request` orchestrator skips the wait — no extra push is needed. (Re-running an existing run does not pick up a new label, because GitHub replays the original event payload.) The trade-off is that any label change starts a fresh PR CI run.
