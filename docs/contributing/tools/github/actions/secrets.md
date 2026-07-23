# CI Secrets 🔐

This page lists every repository secret that GitHub Actions workflows in this repository consume, and documents the failure mode when a secret is missing. For repository **variables** see [configuration.md](configuration.md). For the workflow catalog see [workflows.md](workflows.md).

Repository secrets MUST be set under **Settings → Secrets and variables → Actions → Secrets**.

## Secrets 📋

| Secret | Workflow | Purpose | Required when |
|---|---|---|---|
| `BOT_APP_CLIENT_ID` | [update.yml](../../../../../.github/workflows/update.yml) | GitHub App Client ID (OAuth-style `Iv…` identifier shown on the App's General page) used to mint a short-lived installation token for the update PR. | `CI_ENABLE_AUTO_UPDATES == 'true'` |
| `BOT_APP_PRIVATE_KEY` | [update.yml](../../../../../.github/workflows/update.yml) | PEM-encoded private key of the same GitHub App. Used to sign the JWT that exchanges for the installation token. | `CI_ENABLE_AUTO_UPDATES == 'true'` |

## `BOT_APP_CLIENT_ID` and `BOT_APP_PRIVATE_KEY` 🤖

### Why these secrets exist 🎯

Actions performed with the workflow-provided `GITHUB_TOKEN` do not start further workflow runs. When [update.yml](../../../../../.github/workflows/update.yml) opens an update PR with `GITHUB_TOKEN`, the `pull_request` and `pull_request_target` events that drive [entry-pull-request-change.yml](../../../../../.github/workflows/entry-pull-request-change.yml) do not fire on that PR, so the CI orchestrator never runs against it.

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

1. Open the repository on GitHub.
2. Go to **Settings → Secrets and variables → Actions**.
3. Stay on the **Secrets** tab.
4. Click **New repository secret** and add `BOT_APP_CLIENT_ID` with the App's Client ID (shown on the App's General page under **About**, in the `Iv…` format — *not* the numeric App ID).
5. Click **New repository secret** and add `BOT_APP_PRIVATE_KEY` with the complete PEM content, including the `-----BEGIN PRIVATE KEY-----` and `-----END PRIVATE KEY-----` lines.

### How the workflow consumes the secrets ⚙️

Each PR-opening job in [update.yml](../../../../../.github/workflows/update.yml) runs an `actions/create-github-app-token@v2` step gated on `steps.diff.outputs.changed == 'true'`, then forwards the minted token as `GH_TOKEN` and the resolved `APP_SLUG` to the subsequent PR step. The job's `permissions:` block keeps the workflow-provided `GITHUB_TOKEN` read-only; write access is provided exclusively by the App token, scoped to the App's repository permissions.

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

## Related 🔗

- [configuration.md](configuration.md): repository variables that gate the same workflows.
- [workflows.md](workflows.md): full workflow catalog.
- [pipeline.md](../../../artefact/git/pipeline.md): how the orchestrator routes PR runs.
