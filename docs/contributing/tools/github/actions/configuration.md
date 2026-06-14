# CI Configuration ⚙️

This page lists every repository variable that controls GitHub Actions CI behaviour in this repo. For the workflow catalog see [workflows.md](workflows.md); for the CI flow see [pipeline.md](../../../artefact/git/pipeline.md).

Repository variables are set under **Settings → Secrets and variables → Actions → Variables**.

## Variables 📋

| Variable | Workflow | Default (unset) | Set to activate |
|---|---|---|---|
| `CI_CANCEL_IN_PROGRESS` | [entry-push-latest.yml](../../../../../.github/workflows/entry-push-latest.yml) | Cancels in-progress runs on new push | `false` to keep in-progress runs alive |
| `CI_RUN_ON_MAIN` | [entry-push-latest.yml](../../../../../.github/workflows/entry-push-latest.yml) | Pushes to `main` skip CI | `true` to run CI on `main` pushes too |
| `CI_ENABLE_AUTO_UPDATES` | [update.yml](../../../../../.github/workflows/update.yml), [dependabot-close.yml](../../../../../.github/workflows/dependabot-close.yml) | Update jobs skipped; Dependabot PRs auto-closed | `true` to allow update PRs (workflow-driven and Dependabot) |
| `INFINITO_PLAYWRIGHT_KEEP` | [test-deploy-compose.yml](../../../../../.github/workflows/test-deploy-compose.yml), [test-deploy-universal.yml](../../../../../.github/workflows/test-deploy-universal.yml), [test-deploy-workstation.yml](../../../../../.github/workflows/test-deploy-workstation.yml), [test-deploy-local.yml](../../../../../.github/workflows/test-deploy-local.yml) | Playwright keeps trace, screenshot and video only when a test fails | `true` to keep them for every test (passing runs included) |

## `CI_CANCEL_IN_PROGRESS` 🛑

Controls whether a new push cancels an already-running CI pipeline on the same branch.

**Default behaviour (variable not set or set to any value other than `false`):**
In-progress runs are cancelled when a new push arrives. This is the recommended setting for most workflows.

**To disable cancellation:**

1. Open the repository on GitHub.
2. Go to **Settings → Secrets and variables → Actions**.
3. Switch to the **Variables** tab.
4. Click **New repository variable**.
5. Set **Name** to `CI_CANCEL_IN_PROGRESS` and **Value** to `false`.
6. Save.

**To re-enable cancellation:**

Delete the variable or change its value to anything other than `false` (e.g. `true`).

**How it works:**

```yaml
cancel-in-progress: ${{ vars.CI_CANCEL_IN_PROGRESS != 'false' }}
```

| Variable value | Expression result | Behaviour |
|---|---|---|
| *(not set / empty)* | `'' != 'false'` → `true` | Cancels in-progress runs ✓ |
| `false` | `'false' != 'false'` → `false` | Does **not** cancel ✓ |
| `true` | `'true' != 'false'` → `true` | Cancels in-progress runs ✓ |

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

Controls whether automated update PRs are created. Covers both the workflow-driven jobs in [update.yml](../../../../../.github/workflows/update.yml) (Docker image versions, agent skills) and PRs opened by Dependabot (gated via [dependabot-close.yml](../../../../../.github/workflows/dependabot-close.yml), which auto-closes them).

The workflow-driven jobs additionally require the `BOT_APP_CLIENT_ID` and `BOT_APP_PRIVATE_KEY` repository secrets, see [secrets.md](secrets.md). Without those secrets, runs fail at the token-minting step and no PR is opened.

**Default behaviour (variable not set or set to any value other than `true`):**
The `update-docker-image-versions` and `update-skills` jobs are skipped. Dependabot PRs are auto-closed on open with a comment pointing to this variable.

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

In [update.yml](../../../../../.github/workflows/update.yml) each job carries a job-level guard:

```yaml
if: vars.CI_ENABLE_AUTO_UPDATES == 'true'
```

Dependabot cannot read repository variables itself, so [dependabot-close.yml](../../../../../.github/workflows/dependabot-close.yml) listens on `pull_request_target` (`opened`, `reopened`) and closes any PR authored by `dependabot[bot]` while `CI_ENABLE_AUTO_UPDATES != 'true'`. The workflow does not check out PR code, which keeps the elevated `pull_request_target` context safe.

| Variable value | Workflow update jobs | Dependabot PRs |
|---|---|---|
| *(not set / empty)* | Skipped ✓ | Auto-closed on open ✓ |
| `true` | Run ✓ | Stay open ✓ |
| any other value | Skipped ✓ | Auto-closed on open ✓ |

## `INFINITO_PLAYWRIGHT_KEEP` 🎬

Controls whether Playwright keeps trace, screenshot, and video for every test or only for failing tests across the four deploy-test workflows ([test-deploy-compose.yml](../../../../../.github/workflows/test-deploy-compose.yml), [test-deploy-universal.yml](../../../../../.github/workflows/test-deploy-universal.yml), [test-deploy-workstation.yml](../../../../../.github/workflows/test-deploy-workstation.yml), [test-deploy-local.yml](../../../../../.github/workflows/test-deploy-local.yml)).
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
