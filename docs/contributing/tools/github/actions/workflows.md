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
| [entry-manual.yml](../../../../../.github/workflows/entry-manual.yml): `⚡ CI: Manual` | Manual dispatch of the full orchestrator for a chosen distro set and app whitelist. The `whitelist` input accepts the `__ALL__` sentinel for forced full deploy; see the "Diff-driven app selection" subsection in [pipeline.md](../../../artefact/git/pipeline.md). | manual | `distros` (default `debian`), `whitelist` (optional; `__ALL__` forces full deploy, empty triggers diff derivation, any other value is verbatim), `lifecycles`, `modes` (default `swarm compose`), `priority` (optional; priority line first, regular line runs the rest after it succeeds) |
| [entry-pull-request-cancel.yml](../../../../../.github/workflows/entry-pull-request-cancel.yml): `🚫 Cancel: PR Runs on Close` | Cancels active workflow runs for a PR when it is closed or converted to draft. | auto (`pull_request_target`: closed, converted_to_draft) | none |
| [delete-branch.yml](../../../../../.github/workflows/delete-branch.yml): `🚫 Cancel: Runs on Branch Delete` | Enters the push-entry concurrency group for the deleted branch so that any in-flight run on it is cancelled; a fallback step cancels remaining runs via the API. | auto (`delete`) | none |

### Orchestration 🎵

| Workflow | Description | Trigger | Inputs |
|---|---|---|---|
| [ci-orchestrator.yml](../../../../../.github/workflows/ci-orchestrator.yml): `🎵 CI: Orchestrator` | Central coordinator. Renders a plan table (roles x modes, priority starred, weight-sorted, via `cli.meta.ci.plan`) into the run summary, then runs fork-prereq wait, security, linting, CI image build, code tests, code-quality gate, DNS tests, mirror, deploy tests (optionally split into a priority line and a regular line via `priority`), install tests, development-environment test, `test-guide`, final `done` gate. | reusable | `distros` (default `arch debian ubuntu fedora centos`), `whitelist` (optional), `priority` (optional; app ids deployed first per mode, then excluded from the regular line, which only starts after every priority job succeeded), `image_wait_attempts` (default `1980`), `image_wait_sleep_seconds` (default `10`) |

### Security and linting 🛡️🔍

| Workflow | Description | Trigger | Inputs |
|---|---|---|---|
| [security-codeql.yml](../../../../../.github/workflows/security-codeql.yml): `🔒 Scan: CodeQL (Advanced)` | CodeQL static analysis. Invoked by [ci-orchestrator.yml](../../../../../.github/workflows/ci-orchestrator.yml) so every CI run produces a single scan; additionally runs on a weekly cron so coverage does not drop when no pushes land on `main`. See [pipeline.md](../../../artefact/git/pipeline.md) for the gating behaviour. | reusable, auto (`schedule`: weekly Mon 00:00 UTC) | none |
| [lint.yml](../../../../../.github/workflows/lint.yml): `🧹 Lint` | Runs `make lint` (every lint check in parallel: action, ansible, javascript, makefile, markdown, mermaid, packages, playwright, python, shellcheck) plus a hadolint SARIF job on `Dockerfile`. | reusable, manual | none |

### CI images 🐳

| Workflow | Description | Trigger | Inputs |
|---|---|---|---|
| [images-build-ci.yml](../../../../../.github/workflows/images-build-ci.yml): `🖼️ Build: CI Images (all distros)` | Builds the per-distro CI base images consumed by all test jobs. | reusable | `distros` (required), `checkout_ref` (optional), `image_tag` (default `ci-${github.sha}`), `concurrency_channel` (default `default`) |
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
| [test.yml](../../../../../.github/workflows/test.yml): `🧪 Test` | Runs `make test` (unit, integration, lint and external tests in parallel) on the runner host. | reusable, manual | none |

### Infrastructure tests 🌐📦💻📥

| Workflow | Description | Trigger | Inputs |
|---|---|---|---|
| [test-dns.yml](../../../../../.github/workflows/test-dns.yml): `💬 Test: DNS` | Validates DNS resolution across target distributions. | reusable, manual | `distros` (required on call; default `debian` on manual) |
| [test-deploy-single-node.yml](../../../../../.github/workflows/test-deploy-single-node.yml): `🏝️ Test: Deploy (single-node)` | Single point of truth for the non-swarm deploy tests: fans out to `test-deploy-compose.yml` and `test-deploy-host.yml`, gated per mode via the `modes` input. Called from the orchestrator. | reusable | `distros` (required), `whitelist`, `lifecycles`, `modes` (default `compose host`), `blacklist` (optional; app ids dropped from discovery) |
| [test-deploy-compose.yml](../../../../../.github/workflows/test-deploy-compose.yml): `📦 Test: Deploy (compose)` | Deploy test (compose mode) across all deployment types (`INFINITO_DISCOVER_ALL`; lifecycle-filtered to `alpha beta rc stable`, so `server`/`universal`/`workstation` scopes but not just `web-*`). When `whitelist` is empty, the discover job derives one from the branch's diff vs `origin/main`; see the "Diff-driven app selection" subsection in [pipeline.md](../../../artefact/git/pipeline.md). | reusable | `distros` (required), `whitelist` (optional; explicit value wins over diff), `lifecycles`, `blacklist` (optional) |
| [test-deploy-host.yml](../../../../../.github/workflows/test-deploy-host.yml): `🖥️ Test: Deploy (host)` | Deploy test (host mode) for invokable non-stack roles that configure the host instead of shipping a container stack. Same diff-driven whitelist resolution as `test-deploy-compose.yml`; no Playwright stage (host roles have no web UI). | reusable | `distros` (required), `whitelist` (optional; explicit value wins over diff), `lifecycles`, `blacklist` (optional) |
| [test-deploy-swarm.yml](../../../../../.github/workflows/test-deploy-swarm.yml): `🐝 Test: Deploy (swarm)` | Deploy test (swarm mode) across the full application matrix; each app gets a simulated 3-node DinD cluster with an NFS server, then a drain/reschedule state-survival assertion. Same diff-driven whitelist resolution as `test-deploy-compose.yml`. | reusable, manual | `whitelist` (optional; explicit value wins over diff), `lifecycles`, `blacklist` (optional; reusable trigger only) |
| [test-guide.yml](../../../../../.github/workflows/test-guide.yml): `📖 Test: Guide` | Extracts the `### Production` command from a role README (default `svc-db-postgres`) and executes it against the runner: `<your-server>` becomes `localhost` (ansible_connection local) and the Docker socket replaces the TTY flag. Verifies the documented one-command deploy actually works, seeding the run´s freshly built CI image (needs `images-build-ci.yml`) instead of the published default. Gates the final `done` job. | reusable, manual | `role` (default `svc-db-postgres`) |
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
