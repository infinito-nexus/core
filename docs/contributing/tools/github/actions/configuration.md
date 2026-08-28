# CI Configuration ⚙️

This page lists every repository variable that controls GitHub Actions CI behaviour in this repo. For the workflow catalog see [workflows.md](workflows.md); for the CI flow see [pipeline.md](../../../artefact/git/pipeline.md).

Repository variables are set under **Settings → Secrets and variables → Actions → Variables**.

## Variables 📋

| Variable | Workflow | Default (unset) | Set to activate |
|---|---|---|---|
| `CI_SYNC_MAIN_SOURCE_REPOSITORY` | [entry-push-latest.yml](../../../../../.github/workflows/entry-push-latest.yml) | Syncs `main` from `infinito-nexus/core` before CI scope discovery | `<owner>/<repo>` to use another source, or `false`, empty, or the current repository to skip |
| `CI_RUN_ON_MAIN` | [entry-push-latest.yml](../../../../../.github/workflows/entry-push-latest.yml) | Pushes to `main` skip CI | `true` to run CI on `main` pushes too |
| `CI_ENABLE_AUTO_UPDATES` | [cron-update.yml](../../../../../.github/workflows/cron-update.yml), [entry-pr-open-dependabot-close.yml](../../../../../.github/workflows/entry-pr-open-dependabot-close.yml) | Update jobs skipped; Dependabot PRs auto-closed | `true` to allow update PRs (workflow-driven and Dependabot) |
| `INFINITO_PLAYWRIGHT_KEEP` | [call-test-deploy.yml](../../../../../.github/workflows/call-test-deploy.yml) | Playwright keeps trace, screenshot and video only when a test fails | `true` to keep them for every test (passing runs included) |

## Cancelling in-progress runs 🛑

Not a variable: cancellation is derived from the trigger. Every automatic run on a branch other than `main` is cancelled by a newer run in the same concurrency group; automatic runs on `main` are not, because a half-finished pipeline on the default branch is worse than a queued one. A manual dispatch always supersedes, `main` included: someone typed it, so it is the intent that counts, not the ref.

```yaml
cancel-in-progress: ${{ github.ref_name != 'main' }}
```

`entry-push-latest.yml` declares exactly that expression, and it fires only on `push`, where `github.ref_name` is always the pushed branch. [entry-cancel-superseded.yml](../../../../../.github/workflows/entry-cancel-superseded.yml) carries no concurrency group of its own — it is the API fallback for that group — but its push job repeats the same predicate as a job `if`, so it never touches `main` either.

> ⚠️ **Do not paste that expression into a workflow that listens on `pull_request_target`.** There `github.ref` is the *base* branch, so `github.ref_name` is literally `main` and the rule collapses to a constant `false` — every pull request would stop cancelling its predecessor. `entry-pr-change-orchestrate.yml` therefore declares `cancel-in-progress: true` outright.

[call-orchestrator.yml](../../../../../.github/workflows/call-orchestrator.yml) compares `github.ref` for the same reason: a called workflow inherits the caller's ref, which is `refs/pull/<n>/merge` for a `pull_request` caller but `refs/heads/main` for a `pull_request_target` one. The `ci-orchestrator` job of `entry-pr-change-orchestrate.yml` is fenced to `github.event_name == 'pull_request'`, so the ref the orchestrator sees from that caller is always the merge ref; widening that fence would silently put fork runs into main's group.

`entry-manual-steer.yml` declares `cancel-in-progress: true` outright on its own group, and the orchestrator reads `github.event_name` — which a called workflow inherits from its caller — so a manual sweep supersedes on both levels without an input to pass down.

## `CI_SYNC_MAIN_SOURCE_REPOSITORY` 🔄

Controls whether the push workflow updates the current repository's `main` branch before any later job derives deploy scope from `origin/main`.
This keeps fork branch pushes aligned with the canonical default branch so diff-driven role discovery sees only the branch's own changes.

> ⚠️ **Forced overwrite — do not work in `main`.**
> When the sync runs, the current repository's `main` is **force-pushed** from the source repository's `main`. Any commit that exists only on the fork's `main` is **discarded without warning** on the next push to any covered branch.
> Never commit or merge work directly into `main` on a synced repository. Always work on a `feature/**`, `fix/**`, or `hotfix/**` branch; treat `main` as a read-only mirror of the source.
> If you must use `main` as a working branch, disable the sync first (see **To disable the sync** below).

**Default behaviour (variable not set):**
The workflow uses `infinito-nexus/core` as the source repository.
When the current repository is already `infinito-nexus/core`, the same-repository skip applies.

**To use a different source repository:**

1. Open the repository on GitHub.
2. Go to **Settings → Secrets and variables → Actions**.
3. Switch to the **Variables** tab.
4. Click **New repository variable**.
5. Set **Name** to `CI_SYNC_MAIN_SOURCE_REPOSITORY` and **Value** to `<owner>/<repo>`.
6. Save.

**To disable the sync:**

Set the variable to `false`, `0`, `no`, `off`, `none`, an empty value, or the current repository name.

| Variable value | Behaviour |
|---|---|
| *(not set)* | Uses `infinito-nexus/core`; syncs forks and skips in `infinito-nexus/core` itself ✓ |
| `infinito-nexus/core` in a fork | Syncs the fork's `main` from `infinito-nexus/core` ✓ |
| current repository | Sync skipped ✓ |
| `false`, `0`, `no`, `off`, `none`, or empty | Sync skipped ✓ |

## `CI_RUN_ON_MAIN` 🎯

Controls whether pushes to `main` trigger the CI pipeline. Pushes to all other branches covered by the workflow (`feature/**`, `hotfix/**`, `fix/**`, `alert-autofix-*`) are unaffected.

**Default behaviour (variable not set or set to any value other than `true`):**
Pushes to `main` are gated out at the `run-policy` job and CI is skipped.

**To enable CI on `main` pushes:**

1. Open the repository on GitHub.
2. Go to **Settings → Secrets and variables → Actions**.
3. Switch to the **Variables** tab.
4. Click **New repository variable**.
5. Set **Name** to `CI_RUN_ON_MAIN` and **Value** to `true`.
6. Save.

**To disable again:**

Delete the variable or change its value to anything other than `true`.

**How it works:**

The gate is applied inside [push_ci_policy.sh](../../../../../scripts/meta/resolve/push_ci_policy.sh), which the `run-policy` job invokes. When `GITHUB_REF == refs/heads/main` and `CI_RUN_ON_MAIN != 'true'`, the job emits `should_run=false` and every downstream job is skipped.

| Variable value | Ref is `main` | Behaviour |
|---|---|---|
| *(not set / empty)* | yes | CI skipped ✓ |
| `true` | yes | CI runs ✓ |
| any other value | yes | CI skipped ✓ |
| *(any)* | no | Unaffected (CI runs per branch rules) ✓ |

## `CI_ENABLE_AUTO_UPDATES` 🔄

Controls whether automated update PRs are created. Covers both the workflow-driven jobs in [cron-update.yml](../../../../../.github/workflows/cron-update.yml) (Docker image versions, agent skills) and PRs opened by Dependabot (gated via [entry-pr-open-dependabot-close.yml](../../../../../.github/workflows/entry-pr-open-dependabot-close.yml), which auto-closes them).

The workflow-driven jobs additionally require the `BOT_APP_CLIENT_ID` and `BOT_APP_PRIVATE_KEY` repository secrets, see [secrets.md](secrets.md). Without those secrets, runs fail at the token-minting step and no PR is opened.

**Default behaviour (variable not set or set to any value other than `true`):**
The `update-docker-image-versions` job is skipped. Dependabot PRs are auto-closed on open with a comment pointing to this variable.

**To enable update PRs:**

1. Open the repository on GitHub.
2. Go to **Settings → Secrets and variables → Actions**.
3. Switch to the **Variables** tab.
4. Click **New repository variable**.
5. Set **Name** to `CI_ENABLE_AUTO_UPDATES` and **Value** to `true`.
6. Save.

**To disable again:**

Delete the variable or change its value to anything other than `true`.

**How it works:**

In [cron-update.yml](../../../../../.github/workflows/cron-update.yml) each job carries a job-level guard:

```yaml
if: vars.CI_ENABLE_AUTO_UPDATES == 'true'
```

Dependabot cannot read repository variables itself, so [entry-pr-open-dependabot-close.yml](../../../../../.github/workflows/entry-pr-open-dependabot-close.yml) listens on `pull_request_target` (`opened`, `reopened`) and closes any PR authored by `dependabot[bot]` while `CI_ENABLE_AUTO_UPDATES != 'true'`. The workflow does not check out PR code, which keeps the elevated `pull_request_target` context safe.

| Variable value | Workflow update jobs | Dependabot PRs |
|---|---|---|
| *(not set / empty)* | Skipped ✓ | Auto-closed on open ✓ |
| `true` | Run ✓ | Stay open ✓ |
| any other value | Skipped ✓ | Auto-closed on open ✓ |

## `INFINITO_PLAYWRIGHT_KEEP` 🎬

Controls whether Playwright keeps trace, screenshot, and video for every test or only for failing tests in the deploy-test workflow ([call-test-deploy.yml](../../../../../.github/workflows/call-test-deploy.yml)).
For the full propagation chain, the inventory override, and the local equivalents, see [Playwright Tests](../../../actions/testing/playwright.md#artefact-retention-).

**Default behaviour (variable not set or set to any value other than `true`):**
Artefacts are retained only when a test fails.

**To retain artefacts for every test:**

1. Open the repository on GitHub.
2. Go to **Settings → Secrets and variables → Actions**.
3. Switch to the **Variables** tab.
4. Click **New repository variable**.
5. Set **Name** to `INFINITO_PLAYWRIGHT_KEEP` and **Value** to `true`.
6. Save.

**To disable again:**

Delete the variable or change its value to anything other than `true`.

**How it works:**

Each deploy-test workflow forwards the variable into its own `env:` block:

```yaml
INFINITO_PLAYWRIGHT_KEEP: ${{ vars.INFINITO_PLAYWRIGHT_KEEP }}
```

| Variable value | Behaviour |
|---|---|
| *(not set / empty)* | Trace / screenshot / video kept only on failure ✓ |
| `true` | Trace / screenshot / video kept for every test ✓ |
| any other value | Trace / screenshot / video kept only on failure ✓ |
