# Push, Trigger, Pull

## 1. Free runners

Enumerate every in-progress run across the repository, regardless of branch:

```
gh run list --status in_progress --limit 200 --json databaseId,name,displayTitle,headBranch,workflowName,event,createdAt,url
```

Present the list to the operator and ask which runs should be cancelled to free runners: all, a specific subset, or none. Cancel only what the operator names, one call per id:

```
gh run cancel <id>
```

MUST NOT batch through a shell loop. If the operator answers *"none"*, cancel nothing.

## 2. Push

Target `<branch>` is the branch the operator names. If none is named, the agent MUST NOT silently assume the current branch. Instead, resolve the current branch via `git rev-parse --abbrev-ref HEAD`, propose it to the operator, and wait for explicit confirmation before proceeding. Only after the operator confirms (or names a different branch) is the value frozen as `<branch>`. All subsequent steps operate on the same frozen `<branch>` regardless of what is checked out later. The operator MUST be free to switch branches and keep working while the agent runs.

The agent MUST NOT run `git checkout`, `git switch`, or any other command that changes `HEAD`, stages files, or modifies the working tree. `git push` operates on refs by name and does not require `<branch>` to be checked out. The push goes to the local `origin` remote.

```
git push -u origin <branch>
```

If the push is rejected as non-fast-forward, stop and ask the operator. MUST NOT use `--force` or `--force-with-lease` without explicit per-invocation confirmation.

## 3. Draft the PR

PR target and template rules live in [pull-request.md](./pull-request.md) and MUST be followed before running the commands below.

Query the open PRs for the frozen `<branch>`:

```
gh pr list --head <branch> --state open --json number,isDraft,url
```

Dispatch on the result (GitHub's `state=open` includes both ready and draft PRs; use `isDraft` to distinguish):

- Empty result (no open PR): create one as draft via `gh pr create --draft` using the matching template per [pull-request.md](./pull-request.md).
- Exactly one result with `isDraft == false` (ready PR): run `gh pr ready --undo <number>` on that result's `number` to demote it to draft.
- Exactly one result with `isDraft == true` (already draft): no action.

After any of the three paths above, resolve the PR number for the frozen `<branch>` and freeze it as `<pr-number>` for reuse in Step 5:

```
gh pr list --head <branch> --state open --json number --jq '.[0].number'
```

If the query returns empty or `null`, stop and ask the operator: PR creation silently failed or the branch has no open PR, and Step 5 cannot proceed without `<pr-number>`.

## 4. Trigger Manual CI

Refresh the remote tracking ref first so the diff base is current:

```
git fetch origin main
```

Compute scope from `git diff --name-only origin/main...<branch>`.

- `whitelist`: set to the single role id only if the diff is confined to one `roles/<role>/`; otherwise omit so all roles run.
- `distros`: a change counts as **distro-specific** only if the diff is confined to either
  - files under `packaging/<distro>/` for one or more specific distros, or
  - role tasks gated by a distro conditional (e.g. `when: ansible_os_family == '...'`, `when: ansible_distribution == '...'`), touching only the branches for one or more specific distros.
  Pass those distros as a space-separated list via `-f distros="<distros>"`. In every other case, omit `-f distros`; `entry-manual.yml` then applies its own default (currently `debian` only, it does NOT run all distros).

Before triggering, capture the currently latest run id for this workflow+branch as `<prev-run-id>` (empty string if none exists). This is required so the post-trigger resolve can distinguish the new run from any stale completed run on the same branch:

```
gh run list \
  --workflow=entry-manual.yml \
  --branch=<branch> \
  --event=workflow_dispatch \
  --limit=1 \
  --json databaseId \
  --jq '.[0].databaseId // ""'
```

Then trigger:

```
gh workflow run entry-manual.yml --ref <branch> \
  [-f distros="<distros>"] \
  [-f whitelist="<role>"]
```

`gh workflow run` does NOT print the new run id. Resolve it by repeating the same list query until the returned databaseId is non-empty AND differs from `<prev-run-id>`. That value is `<run-id>`. Each repeat MUST be a separate tool invocation; no shell loop. Do NOT accept a result equal to `<prev-run-id>`; that would attach the watcher to the stale run and return its old exit status immediately.

Watch the new run and propagate its exit status:

```
gh run watch <run-id> --exit-status
```

## 5. Close the loop

- On `success`: `gh pr ready <pr-number>` to mark the PR ready for review.
- On failure: ask the operator whether to follow [ci.md](./debug/ci.md). MUST NOT mark the PR ready for review while the last CI run is failing.
