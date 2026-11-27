# CI Secrets 🔐

This page lists every repository secret that GitHub Actions workflows in this repository consume, and documents the failure mode when a secret is missing. For repository **variables** see [configuration.md](configuration.md). For the workflow catalog see [workflows.md](workflows.md).

Repository secrets MUST be set under **Settings → Secrets and variables → Actions → Secrets**; environment secrets under **Settings → Environments → `<name>` → Environment secrets**.

## Secrets 📋

| Secret | Workflow | Purpose | Required when |
|---|---|---|---|
| `BOT_APP_CLIENT_ID` | [cron-update.yml](../../../../../.github/workflows/cron-update.yml), [cron-collection-source.yml](../../../../../.github/workflows/cron-collection-source.yml) | GitHub App Client ID (OAuth-style `Iv…` identifier shown on the App's General page) used to mint a short-lived installation token for the update PR. An **environment** secret of `updater`, never a repository secret. | `CI_ENABLE_AUTO_UPDATES == 'true'` |
| `BOT_APP_PRIVATE_KEY` | [cron-update.yml](../../../../../.github/workflows/cron-update.yml), [cron-collection-source.yml](../../../../../.github/workflows/cron-collection-source.yml) | PEM-encoded private key of the same GitHub App. Used to sign the JWT that exchanges for the installation token. An environment secret of `updater`. | `CI_ENABLE_AUTO_UPDATES == 'true'` |
| `TRANSLATE_APP_CLIENT_ID` | [entry-pr-translate.yml](../../../../../.github/workflows/entry-pr-translate.yml) | Client ID of the translation App that opens the machine-translation PRs. A repository secret, readable by same-repository pull requests. | `CI_ENABLE_AUTO_TRANSLATIONS == 'true'` |
| `TRANSLATE_APP_PRIVATE_KEY` | [entry-pr-translate.yml](../../../../../.github/workflows/entry-pr-translate.yml) | PEM private key of the translation App. | `CI_ENABLE_AUTO_TRANSLATIONS == 'true'` |
| `MERGE_APP_CLIENT_ID` | [entry-pr-green-update-merge.yml](../../../../../.github/workflows/entry-pr-green-update-merge.yml) | Client ID of the separate merge App, an **environment** secret of `auto-merge`, never a repository secret. | `CI_ENABLE_AUTO_UPDATES == 'true'` |
| `MERGE_APP_PRIVATE_KEY` | [entry-pr-green-update-merge.yml](../../../../../.github/workflows/entry-pr-green-update-merge.yml) | PEM private key of the merge App, an environment secret of `auto-merge`. | `CI_ENABLE_AUTO_UPDATES == 'true'` |
| `API_OPENAI_KEY` | [call-test-deploy.yml](../../../../../.github/workflows/call-test-deploy.yml) | Publishes the `openai/*` models on the LiteLLM gateway and lets the CLI test exercise the route. | Never. Unset leaves the route unpublished. |
| `API_ANTHROPIC_KEY` | [call-test-deploy.yml](../../../../../.github/workflows/call-test-deploy.yml) | Publishes the `anthropic/*` models. | Never. |
| `API_OPENROUTER_KEY` | [call-test-deploy.yml](../../../../../.github/workflows/call-test-deploy.yml) | Publishes `openrouter/auto`. | Never. |
| `DOCKERHUB_USERNAME` | [cron-images-mirror-all.yml](../../../../../.github/workflows/cron-images-mirror-all.yml), [call-images-mirror-missing.yml](../../../../../.github/workflows/call-images-mirror-missing.yml) | Authenticates the mirror job against Docker Hub, which raises the anonymous pull-rate limit the mirror would otherwise hit. | Never. Both workflows declare the secret `required: false` and gate the login step on both values being non-empty. |
| `DOCKERHUB_TOKEN` | [cron-images-mirror-all.yml](../../../../../.github/workflows/cron-images-mirror-all.yml), [call-images-mirror-missing.yml](../../../../../.github/workflows/call-images-mirror-missing.yml) | The access token paired with `DOCKERHUB_USERNAME`. | Never, and only together with the username. |
| `CI_SYNC_MAIN_TOKEN` | [entry-push-latest.yml](../../../../../.github/workflows/entry-push-latest.yml) | Fine-grained token the `🔄 Sync main` job pushes the source repository's `main` with. | In every repository whose `CI_SYNC_MAIN_SOURCE_REPOSITORY` names another repository, which a fork does by default. |

## `CI_SYNC_MAIN_TOKEN` 🔄

### How to create the token 🛠️

1. Open **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token** on the account that owns the fork.
2. Set **Resource owner** to that account and **Repository access** to **Only select repositories**, selecting the fork alone.
3. Grant these repository permissions and nothing else:
   - `Contents`: **Read and write** (force-push of `main`).
   - `Workflows`: **Read and write** (the pushed `main` carries `.github/workflows/**`).
   - `Metadata`: **Read** (default, cannot be removed).
4. Choose an expiration date and note it; an expired token fails the job like a missing one.
5. In the fork, add it under **Settings → Secrets and variables → Actions → Secrets → New repository secret** as `CI_SYNC_MAIN_TOKEN`.

### Failure mode when the secret is missing 💥

| Repository | Behaviour |
|---|---|
| `infinito-nexus/core`, or a repository with the sync disabled through `CI_SYNC_MAIN_SOURCE_REPOSITORY` | The job prints that the sync is skipped and succeeds. The secret is not read. |
| Any other repository | [main_from_repository.sh](../../../../../scripts/github/sync/main_from_repository.sh) fails before any fetch or push and names the secret. The run is marked failed; the other jobs of the run are unaffected. |

## `API_OPENAI_KEY`, `API_ANTHROPIC_KEY`, `API_OPENROUTER_KEY` 🤖

These are optional and fail soft: unset means the provider's route is never
published, and the deployment falls back to whatever local backend the round
deploys. The workflow reads each as `${{ secrets.X || vars.X }}`, so the same
name works as a repository variable; see
[configuration.md](configuration.md#provider-keys-variable-or-secret-) for why
the secret is the better half of that pair.

Set them the same way as the App credentials: **Settings → Secrets and variables
→ Actions → Secrets → New repository secret**, one per provider, the value being
the provider's key verbatim.

The shape each key must have is declared per role rather than here, in
[roles/svc-ai-litellm/meta/secrets.yml](../../../../../roles/svc-ai-litellm/meta/secrets.yml)
with a `type:` and a `regex:`. The pattern rejects a truncated or
whitespace-carrying paste and deliberately accepts any vendor prefix, so a
provider changing its issuance format cannot turn a valid key into a failed
inventory run.

## `BOT_APP_CLIENT_ID` and `BOT_APP_PRIVATE_KEY` 🤖

### Why these secrets exist 🎯

Actions performed with the workflow-provided `GITHUB_TOKEN` do not start further workflow runs. When [cron-update.yml](../../../../../.github/workflows/cron-update.yml) opens an update PR with `GITHUB_TOKEN`, the `pull_request` and `pull_request_target` events that drive [entry-pr-change-orchestrate.yml](../../../../../.github/workflows/entry-pr-change-orchestrate.yml) do not fire on that PR, so the CI orchestrator never runs against it.

Opening the PR through a GitHub App installation token bypasses this restriction. The App counts as a distinct actor, so PR-lifecycle events fire normally and the full CI pipeline runs against every update PR.

### Why a GitHub App and not a PAT 🏷️

A GitHub App installation token SHOULD be used because:

- The token lifetime is bounded to one hour, and a new token is minted on every workflow run.
- Permissions are scoped at the App installation level, independent of any user account.
- No personal account footprint appears in audit logs.

A classic personal access token MAY be used as a fallback for unrelated automation, but it MUST NOT be used here because user-bound credentials expand the blast radius and require manual rotation.

### How to generate the App 🛠️

1. Create a new GitHub App under **Organization settings → Developer settings → GitHub Apps → New GitHub App**.
2. Disable the webhook (uncheck **Active** under **Webhook**). The App MUST NOT receive events.
3. Grant the following repository permissions and nothing else:
   - `Contents`: **Read and write** (the update script force-pushes to `update/*` branches).
   - `Pull requests`: **Read and write** (`gh pr create` / `gh pr edit`).
   - `Metadata`: **Read** (default, cannot be removed).
4. Restrict installation to the owning account only.
5. Generate a private key and download the PEM file.
6. Install the App on the `core` repository only. The App MUST NOT be installed on unrelated repositories.

### How to hand the credentials to CI 📥

`python -m cli.contributing.update.apps --repo infinito-nexus/core --updater-slug infinito-nexus-updater --translate-slug infinito-nexus-translator --downloads ~/Downloads` walks through the steps below and the [translation App](#translate_app_client_id-and-translate_app_private_key-) through `gh`, passing every key on stdin. Done by hand:

1. Open the repository on GitHub.
2. Go to **Settings → Environments → New environment**, name it `updater`, and under **Deployment branches and tags** choose **Selected branches and tags** with the single rule `main`.
3. Under **Environment secrets**, add `BOT_APP_CLIENT_ID` with the App's Client ID (shown on the App's General page under **About**, in the `Iv…` format, *not* the numeric App ID).
4. Add `BOT_APP_PRIVATE_KEY` with the complete PEM content, including the `-----BEGIN PRIVATE KEY-----` and `-----END PRIVATE KEY-----` lines.
5. Delete any repository secret of the same names under **Settings → Secrets and variables → Actions**; a repository secret would stay readable by `pull_request` runs.

### How the workflow consumes the secrets ⚙️

Each PR-opening job in [cron-update.yml](../../../../../.github/workflows/cron-update.yml) and [cron-collection-source.yml](../../../../../.github/workflows/cron-collection-source.yml) declares `environment: updater` and runs an `actions/create-github-app-token@v3` step gated on `steps.diff.outputs.changed == 'true'`, then forwards the minted token as `GH_TOKEN` and the resolved `APP_SLUG` to the subsequent PR step. The job's `permissions:` block keeps the workflow-provided `GITHUB_TOKEN` read-only; write access is provided exclusively by the App token, scoped to the App's repository permissions.

These jobs run on `push` to `main`, `schedule` or `workflow_dispatch` and check out `main`; a dispatch on any other branch fails at the environment's branch rule. No job that declares `updater` may check out or execute pull-request code.

This App MUST NOT be a bypass actor of the `Main` ruleset. It sits on the update-branch ruleset's bypass list beside Dependabot and the admin role, see [Prerequisites for the bypass](#prerequisites-for-the-bypass-).

## `TRANSLATE_APP_CLIENT_ID` and `TRANSLATE_APP_PRIVATE_KEY` 🌐

[entry-pr-translate.yml](../../../../../.github/workflows/entry-pr-translate.yml) mints its token on `pull_request` after running the pull request's own code, so any same-repository pull request can read this key. It therefore belongs to an App of its own that sits on no bypass list: a leaked key grants what every writer already has, and it opens only `translate/pr-*` branches.

1. Create the App as in [How to generate the App](#how-to-generate-the-app-), with `Contents` and `Pull requests`: **Read and write**. Install it on the `core` repository only.
2. Add `TRANSLATE_APP_CLIENT_ID` and `TRANSLATE_APP_PRIVATE_KEY` as **repository** secrets.
3. Never add this App to the bypass list of any ruleset.

### Commit identity propagation 🪪

[pr.sh](../../../../../scripts/github/update/open/pr.sh) reads `APP_SLUG` from the environment and resolves the App's bot user via `gh api /users/<slug>[bot]`. The resolved login and numeric user ID are written into `git config user.name` and `git config user.email` in the `<id>+<slug>[bot]@users.noreply.github.com` form that GitHub accepts for verified commits. When `APP_SLUG` is unset, the script falls back to the `github-actions[bot]` identity. That branch is reached only when the script is invoked outside the workflow, for example a local smoke test where the caller has set `GH_TOKEN` to something other than an App token.

### Failure mode when secrets are missing 💥

A missing secret resolves to an empty string in workflow expressions. The workflow run starts and proceeds normally until the token-minting step:

| Stage | Behaviour when both secrets are missing |
|---|---|
| Workflow parse | Run starts. GitHub emits the warning `The following secrets are referenced but not defined: BOT_APP_CLIENT_ID, BOT_APP_PRIVATE_KEY`. |
| `Generate app token` step | `actions/create-github-app-token` declares both inputs as required and fails with `Error: Input required and not supplied: client-id`. |
| `Open PR if … changed` step | Skipped. Its implicit `if:` condition is `success() && (steps.diff.outputs.changed == 'true')`, and `success()` is false after the token step failed. |
| `pr.sh` | Not executed. No commit, no push, no PR. |
| Outcome | The run is marked failed. GitHub notifies repository admins. No PR is created with a wrong identity. |

The behaviour is fail-loud by design. Missing or mistyped secret names MUST surface as a failed workflow run rather than as a PR with an unintended author.

## `MERGE_APP_CLIENT_ID` and `MERGE_APP_PRIVATE_KEY` 🔀

[entry-pr-green-update-merge.yml](../../../../../.github/workflows/entry-pr-green-update-merge.yml) merges a proven update PR with a second GitHub App that does nothing else. Once enabled, it is the only bypass actor of the `Main` ruleset besides the admins, so its key MUST be reachable from the default branch alone.

### How to set it up 🛠️

1. Create the App as in [How to generate the App](#how-to-generate-the-app-), with `Contents` and `Pull requests`: **Read and write**, plus `Workflows`: **Read and write** so a PR that changes `.github/workflows/` can merge too. Install it on the `core` repository only.
2. Go to **Settings → Environments → New environment**, name it `auto-merge`, and under **Deployment branches and tags** choose **Selected branches and tags** with the single rule `main`. A `pull_request` run, whose ref is the pull request's merge ref, cannot read its secrets. A `pull_request_target` or `workflow_run` job runs with the base branch as its ref and passes this rule, so a job that declares `auto-merge` MUST NOT check out or execute pull-request code; only [entry-pr-green-update-merge.yml](../../../../../.github/workflows/entry-pr-green-update-merge.yml) declares it, and it runs `main`'s own code.
3. Add `MERGE_APP_CLIENT_ID` (the `Iv…` Client ID) and `MERGE_APP_PRIVATE_KEY` (the full PEM) as **environment secrets** of `auto-merge`, never as repository secrets.
4. Only after every prerequisite below holds: in **Settings → Rules → Rulesets → Main**, add the App under **Bypass list** with **For pull requests only**. Check the live bypass list first; it MUST NOT hold the updater App.

### Prerequisites for the bypass 🔒

The merge gate checks who opened the PR, not who pushed its head commit, so the head of an `update/*` or `dependabot/*` branch MUST be writable by the updater App, Dependabot and admins alone, and the updater key MUST be out of reach of every pull request:

1. A branch ruleset on `update/**` and `dependabot/**` restricts creation, updates and deletion, with only the updater App, Dependabot and the admin role on its bypass list. The admin role lets a maintainer merge a translation PR or push a fixup onto an update branch; the translation App stays off it.
2. `BOT_APP_CLIENT_ID` and `BOT_APP_PRIVATE_KEY` exist only as secrets of the `updater` environment, restricted to `main`, and no longer as repository secrets, so no `pull_request` run can read them; [entry-pr-translate.yml](../../../../../.github/workflows/entry-pr-translate.yml) uses the [translation App](#translate_app_client_id-and-translate_app_private_key-). As with `auto-merge`, a `pull_request_target` or `workflow_run` job passes that branch rule, so no job that declares the environment may check out or execute pull-request code; list every workflow that declares it and confirm this before step 4.
3. The updater App's private key was regenerated after the translation workflow stopped minting from it, the new key is the one in `updater`, and every older key is deleted under **Credentials → Key pairs** on the App's settings page. Same-repository pull requests could read the old key, and a copy taken then stays valid until it is revoked.
4. Every open pull request on an `update/**` or `dependabot/**` branch whose head was pushed before prerequisite 3 is closed and its branch deleted; the next updater run and Dependabot open fresh ones from heads pushed after the rotation. The gate checks who opened a pull request, not who pushed its head, so a head pushed with the old key would otherwise stay mergeable through the bypass.

With all four in place, pushing a head the gate accepts needs the updater key, which only workflows on `main` can read. Until then the merge App stays off the bypass list, the merge call fails with HTTP 405, and update PRs wait for a manual merge: the ruleset's `update` rule (Restrict updates) lets only bypass actors move `main`, pull-request merges included, whatever reviews the PR holds.

The job mints the App token only after its merge gate passed, narrowed to `contents`, `pull-requests` and `workflows` write, and uses it for the merge call alone; the gate reads with the read-only `GITHUB_TOKEN`. The job runs on `workflow_run`, which always runs on the default branch, so the environment's branch rule admits it. Without the bypass, the merge call fails with `Repository rule violations found` (HTTP 405) and the PR stays open.

## Related 🔗

- [configuration.md](configuration.md): repository variables that gate the same workflows.
- [workflows.md](workflows.md): full workflow catalog.
- [pipeline.md](../../../artefact/git/pipeline.md): how the orchestrator routes PR runs.
