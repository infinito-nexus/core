# GitHub Actions 🎬

This page catalogs every GitHub Actions workflow defined under the [workflows directory](../../../../../.github/workflows/). It lists each workflow together with a short description, its triggers, and the inputs it accepts.

For the CI **flow** (orchestrator stages, gates, fork-PR handling) see [pipeline.md](../../../artefact/git/pipeline.md). For the **repository variables** that control CI behaviour see [configuration.md](configuration.md). For the **naming and shell-extraction conventions** that every workflow file MUST follow see [workflow.md](../../../artefact/files/github/workflow.md). For the **branch-prefix scopes** referenced by the PR entry workflow see [branch.md](../../../artefact/git/branch.md). For the **mirror architecture** referenced by the image workflows see [mirror.md](../../../artefact/image/mirror.md).

## What GitHub Actions are 📘

GitHub Actions is GitHub's built-in CI/CD system. Each YAML file under `.github/workflows/` is one *workflow*; a workflow contains one or more *jobs*, and each job runs a sequence of *steps* on a hosted or self-hosted runner. Workflows are started by *triggers* declared in the `on:` section. The most common triggers in this repository are:

- `push`: fires when commits land on a branch.
- `pull_request` / `pull_request_target`: fires on PR lifecycle events (`opened`, `synchronize`, `reopened`, `ready_for_review`, `closed`, `converted_to_draft`). The `_target` variant runs with the base-branch secrets and is used to grant fork PRs controlled access to privileged steps.
- `schedule`: cron-based periodic runs (UTC).
- `workflow_dispatch`: manual run from the GitHub UI or `gh workflow run`, optionally with inputs.
- `workflow_call`: the workflow is a *reusable workflow* and is only started by another workflow that calls it via `uses:`.
- `delete`: fires when a branch or tag is deleted.

Workflows communicate through *inputs* (on `workflow_call` / `workflow_dispatch`), *outputs*, *concurrency groups* (which cancel or serialize runs with the same group key), and the `GITHUB_TOKEN` / repository secrets and variables. The entry points of this repository (`entry-*.yml`) translate external triggers into a call to the central [ci-orchestrator.yml](../../../../../.github/workflows/ci-orchestrator.yml). Most other workflows are reusable building blocks invoked from the orchestrator.

## Workflow catalog 📚

Trigger column legend: **auto** = fires automatically (push, pull_request, schedule, delete); **manual** = `workflow_dispatch`; **reusable** = `workflow_call`. Multiple values mean the workflow accepts any of them.

### Entry points 🚪

| Workflow | Description | Trigger | Inputs |
|---|---|---|---|
| [entry-pull-request-change.yml](../../../../../.github/workflows/entry-pull-request-change.yml): `⚡ CI: Pull Request` | Detects PR scope from changed files + branch prefix, then conditionally calls the orchestrator. A maintainer `🛡️ Trusted` label builds the privileged images from the PR head — see [pipeline.md](../../../artefact/git/pipeline.md#trusted-fork-prs-). A `🧩 Subset` label pins the deploy matrix to the roles listed in the PR body — see [pipeline.md](../../../artefact/git/pipeline.md#subset-label-). | auto (`pull_request` & `pull_request_target`: opened, synchronize, reopened, ready_for_review, labeled) | none |
| [entry-push-latest.yml](../../../../../.github/workflows/entry-push-latest.yml): `⚡ CI: Push` | Syncs `main` from the configured source repository, then runs the orchestrator on pushes to `main`, `feature/**`, `hotfix/**`, `fix/**`, `chore/**`, `alert-autofix-*`; on tagged `main` it also calls `release-version.yml`. Respects the `CI_CANCEL_IN_PROGRESS`, `CI_SYNC_MAIN_SOURCE_REPOSITORY`, and `CI_RUN_ON_MAIN` repository variables, see [configuration.md](configuration.md). | auto (`push`) | none |
| [entry-manual.yml](../../../../../.github/workflows/entry-manual.yml): `⚡ CI: Manual` | Manual dispatch of the full orchestrator for a chosen distro set and app whitelist. The `whitelist` input accepts the `__ALL__` sentinel for forced full deploy; see the "Diff-driven app selection" subsection in [pipeline.md](../../../artefact/git/pipeline.md). | manual | `distros` (default `debian`), `whitelist` (optional; `__ALL__` forces full deploy, empty triggers diff derivation, any other value is verbatim) |
| [entry-pull-request-cancel.yml](../../../../../.github/workflows/entry-pull-request-cancel.yml): `🚫 Cancel: PR Runs on Close` | Cancels active workflow runs for a PR when it is closed or converted to draft. | auto (`pull_request_target`: closed, converted_to_draft) | none |
| [delete-branch.yml](../../../../../.github/workflows/delete-branch.yml): `🚫 Cancel: Runs on Branch Delete` | Enters the push-entry concurrency group for the deleted branch so that any in-flight run on it is cancelled; a fallback step cancels remaining runs via the API. | auto (`delete`) | none |

### Orchestration 🎵

| Workflow | Description | Trigger | Inputs |
|---|---|---|---|
| [ci-orchestrator.yml](../../../../../.github/workflows/ci-orchestrator.yml): `🎵 CI: Orchestrator` | Central coordinator. Runs fork-prereq wait, security, linting, CI image build, code tests, code-quality gate, DNS tests, mirror, deploy tests, install tests, development-environment test, final `done` gate. | reusable | `distros` (default `arch debian ubuntu fedora centos`), `whitelist` (optional), `image_wait_attempts` (default `1980`), `image_wait_sleep_seconds` (default `10`) |

### Security and linting 🛡️🔍

| Workflow | Description | Trigger | Inputs |
|---|---|---|---|
| [security-codeql.yml](../../../../../.github/workflows/security-codeql.yml): `🔒 Scan: CodeQL (Advanced)` | CodeQL static analysis. Invoked by [ci-orchestrator.yml](../../../../../.github/workflows/ci-orchestrator.yml) so every CI run produces a single scan; additionally runs on a weekly cron so coverage does not drop when no pushes land on `main`. See [pipeline.md](../../../artefact/git/pipeline.md) for the gating behaviour. | reusable, auto (`schedule`: weekly Mon 00:00 UTC) | none |
| [lint-ansible.yml](../../../../../.github/workflows/lint-ansible.yml): `🔍 Lint: Ansible` | Runs `make lint-ansible`. | reusable | none |
| [lint-docker.yml](../../../../../.github/workflows/lint-docker.yml): `🔍 Lint: Dockerfiles` | hadolint on `Dockerfile` with SARIF upload. | reusable | none |
| [lint-python.yml](../../../../../.github/workflows/lint-python.yml): `🔍 Lint: Python` | `ruff` over the Python sources. | reusable | none |
| [lint-shell.yml](../../../../../.github/workflows/lint-shell.yml): `🔍 Lint: Shell Scripts` | `shellcheck` over every `*.sh` file. | reusable | none |
| [lint-packages.yml](../../../../../.github/workflows/lint-packages.yml): `🔍 Lint: Packages` | Validates the generated distro packaging metadata (`debian/changelog` via `dpkg-parsechangelog`, the Fedora spec via `rpmspec`, the Arch `PKGBUILD` via `bash -n`) so a malformed changelog is caught before the package build. | reusable | none |

### CI images 🐳

| Workflow | Description | Trigger | Inputs |
|---|---|---|---|
| [images-build-ci.yml](../../../../../.github/workflows/images-build-ci.yml): `🐳 Build: CI Images (all distros)` | Builds the per-distro CI base images consumed by all test jobs. | reusable | `distros` (required), `checkout_ref` (optional), `image_tag` (default `ci-${github.sha}`), `concurrency_channel` (default `default`) |
| [images-cleanup-ci.yml](../../../../../.github/workflows/images-cleanup-ci.yml): `🧹 Images: Cleanup CI (GHCR)` | Deletes CI images from GHCR older than N days. | auto (`schedule`: weekly Mon 00:00 UTC), manual | `days` (default `7`) |

### Image mirroring 🪞

| Workflow | Description | Trigger | Inputs |
|---|---|---|---|
| [images-mirror-missing.yml](../../../../../.github/workflows/images-mirror-missing.yml): `🪞 Mirror: Docker Hub → GHCR (only missing)` | Mirrors only the upstream images that are not yet in GHCR. Called from the orchestrator before deploy tests. | reusable | `ghcr_namespace`, `ghcr_prefix` (default `mirror`), `repo_root` (default `.`), `source_repository`, `source_ref`, plus throttling knobs |
| [images-mirror-all.yml](../../../../../.github/workflows/images-mirror-all.yml): `🪞 Mirror: Docker Hub → GHCR` | Full nightly mirror of every referenced upstream image into GHCR. | auto (`schedule`: daily 00:00 UTC), manual | `ghcr_namespace`, `ghcr_prefix` (default `mirror`), `repo_root` (default `.`), `images_per_hour` (throttle) |
| [images-mirror-cleanup.yml](../../../../../.github/workflows/images-mirror-cleanup.yml): `🧹 Images: Cleanup GHCR (Private)` | Deletes GHCR mirror packages by prefix and visibility. Supports `dry_run`. | manual | `ghcr_namespace`, `ghcr_prefix` (default `mirror`), `visibility` (`private`/`public`/`internal`, default `private`), `dry_run` |

### Code tests 🧪

| Workflow | Description | Trigger | Inputs |
|---|---|---|---|
| [test-code-unit.yml](../../../../../.github/workflows/test-code-unit.yml): `🧪 Test: Code (Units)` | Runs `make test-unit` in the CI container. | reusable | none |
| [test-code-integration.yml](../../../../../.github/workflows/test-code-integration.yml): `🧪 Test: Code (Integration)` | Runs `make test-integration` in the CI container. | reusable | none |
| [test-code-lint.yml](../../../../../.github/workflows/test-code-lint.yml): `🧪 Test: Code (Lint)` | Runs the project's own lint tests (not the external linters). | reusable | none |
| [test-code-external.yml](../../../../../.github/workflows/test-code-external.yml): `🧪 Test: Code (External)` | Runs `make test-external` against external services. | reusable, manual | none |

### Infrastructure tests 🌐📦💻📥

| Workflow | Description | Trigger | Inputs |
|---|---|---|---|
| [test-dns.yml](../../../../../.github/workflows/test-dns.yml): `💬 Test: DNS` | Validates DNS resolution across target distributions. | reusable, manual | `distros` (required on call; default `debian` on manual) |
| [test-deploy-server.yml](../../../../../.github/workflows/test-deploy-server.yml): `📦 Test: Deploy (server)` | Deploy test for server and `web-*` roles. When `whitelist` is empty, the discover job derives one from the branch's diff vs `origin/main`; see the "Diff-driven app selection" subsection in [pipeline.md](../../../artefact/git/pipeline.md). | reusable | `distros` (required), `whitelist` (optional; explicit value wins over diff) |
| [test-deploy-universal.yml](../../../../../.github/workflows/test-deploy-universal.yml): `📦 Test: Deploy (universal)` | Deploy test for shared system roles. Same diff-driven whitelist resolution as `test-deploy-server.yml`. | reusable | `distros` (required), `whitelist` (optional; explicit value wins over diff) |
| [test-deploy-workstation.yml](../../../../../.github/workflows/test-deploy-workstation.yml): `📦 Test: Deploy (workstation)` | Deploy test for workstation and `desk-*` roles. Same diff-driven whitelist resolution as `test-deploy-server.yml`. | reusable | `distros` (required), `whitelist` (optional; explicit value wins over diff) |
| [test-deploy-local.yml](../../../../../.github/workflows/test-deploy-local.yml): `📦 Test: Deploy (local)` | Local/self-hosted deploy test. Intended for `act` or manual dispatch, not part of the orchestrator. Does NOT apply the diff-driven whitelist resolution; the input is used verbatim. | manual | `test_deploy_type` (`server`/`universal`/`workstation`, default `server`), `distros` (default `debian`), `whitelist` (optional) |
| [test-install-make.yml](../../../../../.github/workflows/test-install-make.yml): `📥 Test: Install Make` | Validates the `make install` entry points. | reusable | none |
| [test-install-pkgmgr.yml](../../../../../.github/workflows/test-install-pkgmgr.yml): `📥 Test: Install Package Manager` | Validates installation via the upstream package manager. | reusable | none |
| [test-environment.yml](../../../../../.github/workflows/test-environment.yml): `💻 Test: Development Environment` | Builds and exercises the dev-runtime image matrix. | reusable, manual | none |

### Release and maintenance 🚀🔄

| Workflow | Description | Trigger | Inputs |
|---|---|---|---|
| [release-version.yml](../../../../../.github/workflows/release-version.yml): `🚀 Release: Version Logic` | Releases a specific version tag (build + publish). Called from `entry-push-latest.yml` on tagged pushes. | reusable, manual | `tag` (required, e.g. `v1.2.3`) |
| [release-highest.yml](../../../../../.github/workflows/release-highest.yml): `🚀 Release: Highest Missing Version` | Scheduled backfill: finds the highest tag without a release and triggers `release-version.yml` for it. | auto (`schedule`: daily 00:00 UTC), manual | none |
| [cleanup-stale.yml](../../../../../.github/workflows/cleanup-stale.yml): `🧹 Cleanup: Stale Repository Data` | Marks and closes stale issues and PRs, deletes inactive branches, and prunes old GHCR CI image versions. | auto (`schedule`: daily 00:00 UTC), manual | none |
| [update.yml](../../../../../.github/workflows/update.yml): `🔄 Update: Versions` | Updates Docker image versions and other pinned dependencies; opens an update PR via a GitHub App installation token so PR-lifecycle events fire on the resulting PR. Both jobs are gated behind the `CI_ENABLE_AUTO_UPDATES` repository variable, see [configuration.md](configuration.md). Requires the `BOT_APP_CLIENT_ID` and `BOT_APP_PRIVATE_KEY` repository secrets, see [secrets.md](secrets.md). | auto (`push` to `main`, `schedule`: daily 00:30 UTC), manual | none |
| [dependabot-close.yml](../../../../../.github/workflows/dependabot-close.yml): `🚫 Dependabot: Close while auto-updates disabled` | Auto-closes Dependabot PRs while `CI_ENABLE_AUTO_UPDATES` is not set to `true`, so Dependabot honours the same gate as the workflow-driven update jobs. See [configuration.md](configuration.md). | auto (`pull_request_target`: opened, reopened) | none |

## Changing workflows ✍️

Before adding or editing a workflow file:

1. Follow the naming schema and shell-extraction rules in [workflow.md](../../../artefact/files/github/workflow.md).
2. If the change affects the CI flow (stages, gates, order), also update [pipeline.md](../../../artefact/git/pipeline.md).
3. If the change adds or removes a repository variable, also update [configuration.md](configuration.md).
4. Update the relevant row in this page so the catalog stays accurate.
