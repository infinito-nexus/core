# Claude Code Settings 🤖

This page documents the permission and runtime configuration in [`.claude/settings.json`](../../../../../.claude/settings.json).
For the trust assumptions and the two-layer containment model behind these rules, see [security.md](security.md).
For the OS-level sandbox configuration, see [sandbox.md](sandbox.md).
For general agent workflow rules, see [common.md](../common.md).
For the Claude Code reference, see [docs.claude.com](https://code.claude.com/docs/en/settings).

## Permission Model 🔐

Claude Code evaluates each tool call against the lists in [`permissions`](../../../../../.claude/settings.json):

| List | Behavior |
|---|---|
| `allow` | Executes automatically without prompting. |
| `ask` | Pauses and asks the operator for approval before executing. |
| `deny` | Rejects the call unconditionally, even if `allow` would otherwise match. |

`deny` takes precedence over `allow`. `settings.local.json` MAY extend project permissions locally but MUST NOT weaken `deny` rules defined here.

For Bash specifically, the wildcard allow entry `Bash(*)` auto-allows every invocation that does not match a `deny` or `ask` rule. The legacy `sandbox.autoAllowBashIfSandboxed: true` flag remains enabled as defence-in-depth, but the `Bash(*)` entry is now the primary gate, so shell shapes the sandbox heuristic used to decline (env-prefixes, `&&`/`|` chains, quoted multi-word args, redirections) no longer need per-shape allow entries.

## Allow Permissions ✅

The allowlist covers the `Bash(*)` wildcard plus the non-Bash tools (`Read`, `Edit`, `Write`, `WebSearch`) and per-domain `WebFetch` entries (the wildcard form is inert, see row below). The real gating for Bash lives in the `ask` and `deny` lists below: mutating `gh`/`docker`/`git` shapes land in `ask`, and structurally destructive shapes (`rm -rf*`, `sudo*`, shell loops, `git push --force*`, mutating `gh api` verbs, etc.) are blocked outright by `deny`. The sandbox (`allowWrite`, `denyRead`, `allowedDomains`) bounds the blast radius of everything that does execute.

| Permission | When | Why | Security |
|---|---|---|---|
| `Bash(*)` | Every shell invocation the agent makes: `make` targets, `git`/`gh`/`docker` calls, `grep`/`head`/`tail`/`wc`, Python test runners, log-capture pipelines, etc. | A single wildcard replaces 15+ per-shape entries (`* make *`, `docker *`, `gh api *`, `grep *`, `head *`, `tail *`, `tee *`, `wc *`, `echo *`, `pkill *`, `* > /tmp/*`, `*=* python* *`, `gh issue *`, `gh run *`, `make *`) that existed purely as workarounds for the sandbox auto-allow heuristic declining on env-prefixes, redirects, pipes, and quoted args. With `Bash(*)` the allowlist no longer rots as new command shapes emerge; the gating responsibility moves entirely to `ask` (mutating verbs) and `deny` (structurally unsafe shapes). | The sandbox (`allowWrite`, `denyRead`, `allowedDomains`, see [sandbox.md](sandbox.md)) bounds every write, every read, and every outbound connection. `deny` rules block destructive patterns unconditionally; `ask` rules force operator review on every mutating `gh`/`docker`/`git commit`/`Skill(update-config*)` invocation. The wildcard does **not** loosen any existing guardrail; it only drops the per-shape workarounds. |
| `Read` | Every task that inspects a file. | Core IDE operation. The agent cannot understand code without it. | Scope is limited by `denyRead` in the sandbox configuration (see [sandbox.md](sandbox.md)). Credential directories are never readable. |
| `Edit` | Every task that modifies an existing file. | Core IDE operation. Required for any code change. | Write scope is bounded by `allowWrite` (see [sandbox.md](sandbox.md)). Changes outside the paths listed there are blocked. |
| `Write` | Every task that creates a new file. | Core IDE operation. Required for scaffolding and new file creation. | Same sandbox boundary as `Edit`. |
| `WebSearch` | Looking up documentation, error messages, or package information. | Allows the agent to resolve unknown APIs and tooling questions without leaving the terminal. | Outbound query only. No local data is uploaded. |
| `WebFetch(domain:github.com)` / `WebFetch(domain:raw.githubusercontent.com)` / `WebFetch(domain:docs.decidim.org)` | Fetching repository pages, issue/PR views, raw file content, and project-specific upstream docs (currently Decidim). These form the near-daily baseline for this project's web research. | An explicit per-domain allowlist is required because the wildcard form `WebFetch(domain:*)` is **inert**: observed empirically, the permission prompt still fires for every new host despite the wildcard being present, so the wildcard buys nothing. Contributors who need a new origin MUST extend this list (and the sandbox `allowedDomains` in [sandbox.md](sandbox.md)) explicitly. | Read-only HTTP fetches. Credentials in URLs are still discouraged. Egress is bounded by the sandbox network configuration (see [sandbox.md](sandbox.md)) and any host-level firewall. |

### Gating Model for Bash 🚦

Because Bash is allowed wholesale, the operational safety of shell invocations rests on three layers, in order of precedence:

1. **`deny`** (precedence 1): structurally destructive shapes are blocked outright, even when sandboxed. Covers shell loops (`for`/`while`/`until`), cross-repo `git -C *`, force-push/reset/clean/amend, `rm -rf*`, `sudo*`, privileged `gh` verbs (`secret`/`ssh-key`/`gpg-key`/`variable`/`extension`/`workflow enable`/`workflow disable`/`repo delete`/`pr merge`/`issue transfer`), and mutating `gh api` verbs (`DELETE`/`PUT`, secrets/keys/collaborators/merge paths).
2. **`ask`** (precedence 2): mutating `gh`/`docker`/`git` verbs and `Skill(update-config*)` pause for operator review. Every image mutation (`docker run`/`build`/`push`/`login`), `gh api` with a non-GET verb or a body-flag or `graphql`, every known `gh` mutating verb (21 of them via `gh * <verb>*`), `git commit*`, and anything touching `.claude/settings.json` routes through here.
3. **Sandbox** (precedence 3): everything else runs under `allowWrite` / `denyRead` / `allowedDomains`. Writes outside `allowWrite` fail with `EROFS`; reads from `~/.ssh`, `~/.gnupg`, `~/.aws`, etc. are denied; outbound connections to anything not in `allowedDomains` fail.

The `sandbox.autoAllowBashIfSandboxed: true` flag is retained as belt-and-suspenders. If `Bash(*)` were ever removed, the sandbox auto-allow would still cover the common shapes, but it is no longer the primary gate.

Consequences in practice:

- **No allowlist edits** are needed when introducing new make targets, scripts, tooling, or shell shapes (redirects, pipes, env-prefixes, quoted args).
- **Read-only inspection commands** (`grep`, `find`, `ls`, `cat`, `git log`, `docker ps`, etc.) just work.
- **Mutating commands that stay inside `allowWrite`** (e.g. `make test`, `pip install`, `docker build`, though builds still route through `ask`) just work under the sandbox.
- **Mutating commands that target paths outside `allowWrite`** (e.g. `mv ~/file /etc/`) fail at the sandbox layer with EROFS.
- **Outbound network calls** are bounded by `sandbox.network.allowedDomains` (see [sandbox.md](sandbox.md)).

The trade-off is that `deny` now carries the full weight of "what the agent must never do from the shell". New destructive patterns MUST be added to `deny`. They can no longer be caught implicitly by an absent `allow` entry.

## Ask Permissions ⚠️

These operations pause and require explicit operator approval before executing, even when sandboxed.

| Permission | When | Why approval is required | Security |
|---|---|---|---|
| `git commit*` | Creating a permanent history entry. | The operator MUST review the staged diff and message before committing. | Commits are persistent and visible to all contributors after push. |
| `git push*` | Publishing changes to the remote. | Cannot be undone without a force-push. | Exposes changes to all repository collaborators and CI. |
| `docker run*` / `docker * run*` | Starting a container. The bare `docker run*` pattern catches the direct form; the middle-wildcard `docker * run*` pattern catches the `docker container run` synonym (and any future `docker <namespace> run` spelling) in a single rule. | Each invocation carries a unique risk profile depending on flags. `docker run` can mount host paths (`-v /:/host`), expose privileged capabilities (`--privileged`, `--cap-add`), bypass the sandbox via the Docker daemon's root privileges, and pull arbitrary images from any reachable registry. Middle-wildcard false positives (e.g. a container name containing " run") land here as harmless extra prompts, an acceptable trade-off against per-synonym enumeration. | Can mount host paths, expose ports, and run privileged containers. This is why the rule stays in `ask` even though the broader `Bash(*)` allow is active. |
| `docker build*` / `docker * build*` | Building a Docker image. Bare `docker build*` catches the direct form; `docker * build*` catches the `docker image build` and `docker buildx build` synonyms namespace-wide. | Image builds execute arbitrary instructions from a `Dockerfile` as root inside a build container, pull arbitrary base images from any reachable registry, and can exfiltrate host files via `COPY` from the build context. | Reviewer MUST confirm the Dockerfile path, build context, and target tag. |
| `docker push*` / `docker * push*` | Publishing an image to a registry. Bare `docker push*` catches the direct form; `docker * push*` catches the `docker image push` synonym. | Registry pushes are remotely-visible and irreversible from the client; pushing to the wrong registry or tag can overwrite existing images consumed by downstream deployments. Authentication state is a persistent side-effect (uses the previously-saved `docker login` credentials). | Reviewer MUST confirm the target registry, repository, and tag before approval. |
| `docker login*` | Storing registry credentials in the local Docker config (`~/.docker/config.json`). | Persistent credential material that survives beyond the session and is consumed by every subsequent `docker push`/`pull`. Login prompts can also leak passwords into the transcript if entered interactively. Only one spelling exists, so no synonym wildcard is needed. | Reviewer MUST confirm the registry URL. If a password is passed via `--password` / `--password-stdin`, the reviewer MUST also confirm that no credential lands in the transcript. |
| `gh api * -X *` / `gh api * --method *` | Any explicit non-GET HTTP verb against the GitHub API. | The default `gh api` verb is GET (read-only). Specifying `-X` or `--method` always indicates a write (POST/PATCH/DELETE/PUT), so the prompt forces a per-call review. PUT and DELETE are blocked outright by `deny`; POST and PATCH land here. | Captures every mutating call regardless of endpoint. The DELETE/PUT-specific deny rules below take precedence and reject those verbs unconditionally. |
| `gh api * -f *` / `gh api * -F *` / `gh api * --field *` / `gh api * --raw-field *` / `gh api * --input *` | Any `gh api` invocation that sets a request body via `gh`'s body-flags (short, long, or file-input spellings). | `gh api` switches implicitly from GET to POST as soon as a body-flag is present; no explicit `-X`/`--method` is required. Without these ask rules the broad `Bash(*)` allow would let body-carrying `gh api` POSTs through silently. Short forms (`-f`, `-F`), long forms (`--field`, `--raw-field`), and file input (`--input`) are all listed so no spelling slips past. A future gh-CLI body-flag would need to be added here explicitly. | Captures every implicit-POST `gh api` call. Path-based deny rules (`secrets`, `keys`, `collaborators`, `merge`, DELETE/PUT) still take precedence. |
| `gh api graphql*` | Any call to the GraphQL endpoint. | GraphQL mutations bypass the REST-path-based deny rules entirely. A `mutation { … }` can achieve write effects (label manipulation, project-item creation, issue transfers, etc.) whose REST equivalents are denied by path. The whole endpoint is asked regardless of query direction because `gh api` cannot distinguish a read query from a mutation at the command line; body-flag ask rules also fire for graphql invocations that pass `-f query=…`, providing defence in depth. | Every GraphQL invocation requires per-call review. Path-based deny rules do not apply because GraphQL does not use resource-path URIs; the ask prompt is the primary gate. |
| `gh api enterprises/*:*` | Any enterprise-scoped API call. | Enterprise endpoints administer org membership, billing, and policy across multiple orgs. | Reviewer MUST confirm the enterprise slug and intended scope. |
| `gh api orgs/*:*` | Any organization-scoped API call. | Org endpoints govern membership, teams, and org-wide settings. | Reviewer MUST confirm the org and the specific endpoint. |
| `gh api repos/*/actions/permissions*:*` | Reading or mutating Actions permissions on a repo. | Toggles whether forks may run workflows, restricts the action allowlist, and gates repo-level CI policy. | Reviewer MUST confirm the policy delta before approval. |
| `gh api repos/*/actions/workflows/*/dispatches:*` | Triggering a workflow via `workflow_dispatch`. | Equivalent in effect to `gh workflow run`, which runs CI with workflow secrets and produces remotely-visible results. | Reviewer MUST confirm the workflow ref and inputs payload. |
| `gh api repos/*/branches/*/protection*:*` | Reading or mutating branch protection on a specific branch. | Branch protection gates pushes, merges, and required checks. PUT is already blocked unconditionally; this pattern catches GET-audit and explicit-PATCH paths. | Reviewer MUST confirm the rule delta. |
| `gh api repos/*/environments*:*` | Reading or mutating Actions environments. | Environments gate deployment secrets and required reviewers; weakening them exposes secrets to additional workflows. | Reviewer MUST confirm the environment and gating change. |
| `gh api repos/*/hooks*:*` | Reading or mutating repository webhooks. | Hooks deliver events to external systems; misconfiguration can leak data or break integrations. | Each call MUST be reviewed for target URL and event scope. |
| `gh api repos/*/releases*:*` | Reading or mutating GitHub releases. | Release creation and asset uploads are user-visible publishing actions. | Reviewer MUST confirm the tag and asset payload before approval. |
| `gh api repos/*/rulesets*:*` | Reading or mutating branch/tag rulesets (branch protection successor). | Rulesets gate merges and pushes; weakening them affects every contributor. | Each call MUST be reviewed for the rule scope and required-checks impact. |
| `gh api teams/*:*` | Any team-scoped API call. | Team endpoints govern membership and permission grants. | Reviewer MUST confirm the team and intended change. |
| `gh * <verb>*` (archive, cancel, close, comment, create, delete, develop, edit, fork, link, lock, pin, ready, rename, reopen, rerun, review, unlink, unlock, unpin, upload) | Any `gh` CLI invocation whose second token is a known mutating verb. | The wildcard in the namespace slot collapses 21 mutating verbs across `gh issue/pr/release/repo/ruleset/run/cache/gist/label/project/…` into a single rule per verb. Future namespaces that ship the same verb (e.g. a hypothetical `gh discussion lock`) are caught automatically. Explicit per-namespace lists rot as the `gh` CLI grows. | Read-only subcommands (`view`, `list`, `status`, `diff`, `checks`, `watch`, `download`, `clone`) do not match and remain auto-allowed via the sandbox, mirroring the GET-vs-mutation split used for `gh api`. The `deny` rules above take precedence for the highest-blast verbs (e.g. `gh repo delete`, `gh secret *`, `gh ssh-key *`). |
| `gh * field-*` / `gh * item-*` / `gh * mark-template*` / `gh * unmark-template*` | Compound subcommands (e.g. `gh project item-create`, `gh project field-delete`, `gh project mark-template`). | The single-token `gh * <verb>*` patterns above only match when the third token starts with the verb. Compound names like `item-create` or `mark-template` slip through because the third token is the full compound, not the bare verb. These rules close that gap for Projects v2 mutations namespace-wide. | Catches all current and future compound-verb mutations without requiring per-verb enumeration. |
| `gh auth *` | Any `gh auth` subcommand (login, logout, refresh, setup-git, status, switch, token). | Whole namespace asked: `logout` is operator-scope DoS; `token` prints the OAuth/PAT to stdout where it would land in the transcript permanently if approved (operator MUST decline unless they explicitly want the token captured); `switch` silently changes the active identity; `setup-git` rewrites global git config; `login`/`refresh`/`status` are lower-risk but kept inside the same gate for symmetry. The trade-off vs. an explicit `deny` on `logout`/`token` is that approval is now a single click; operators must read the prompt before tapping through. | Reviewer MUST confirm intent for every invocation; in particular `gh auth token` MUST be declined unless the operator deliberately wants the token in the transcript. |
| `gh codespace *` | Any codespace subcommand (create, ssh, cp, delete, ports, …). | Codespaces are billable, persistent VMs with full repo + secret access; `ssh`/`cp` open a remote shell or move files in/out. The whole namespace is asked because even read commands (`list`, `view`) interact with billable infrastructure. | Each invocation MUST be reviewed individually for billing + data-flow impact. |
| `gh config set*` | Sets a `gh` CLI config key. | `gh config set editor /tmp/evil.sh` plants a binary that runs the next time any `gh` subcommand opens an editor (e.g. `gh issue create` without `--body`), a deferred-execution backdoor that survives the current session. Persistent CLI config belongs to a deliberate operator decision. | Reviewer MUST confirm the key and value, especially for `editor`, `pager`, `git_protocol`. |
| `gh label clone*` | Copies all labels from one repository into another. | Mutation against the destination repo. Verb `clone` is not in the wildcard list because it is otherwise read-only-ish (e.g. `gh repo clone` is just a git clone). | Reviewer MUST confirm both source and destination repos. |
| `gh pr checkout*` | Switches the local working tree to a PR branch. | Does not check for uncommitted changes by default; silently overwrites them. The risk is to local state, not remote, but the loss is unrecoverable. | Reviewer MUST confirm the working tree is clean (or stashed) before approving. |
| `gh project copy*` | Duplicates an entire Projects v2 board. | Verb `copy` is not in the wildcard list. The duplicate is created under the operator's identity and may be public-by-default depending on org settings. | Reviewer MUST confirm the source/destination owners and visibility. |
| `gh repo set-default*` | Sets the default repository for `gh` invocations in the current directory. | Mutates per-directory `gh` config; subsequent ambiguous `gh pr/issue/run` calls would silently target the new default, which can mis-route mutations. Verb `set-default` is not in the wildcard list. | Reviewer MUST confirm the new default repository. |
| `gh repo sync*` | Syncs a fork against its upstream. | Pulls upstream commits into the fork (the operator's repo). Verb `sync` is not in the wildcard list because `gh repo clone`-style reads use related verbs that should remain frictionless. | Reviewer MUST confirm the source/destination repos and that the local working tree tolerates the sync. |
| `gh workflow run*` | Triggering a CI workflow run on the remote. | Consumes runner minutes, executes with workflow secrets, and produces remotely-visible results. Equivalent in effect to `git push` for triggered runs. The verb is `run`, which is not in the wildcarded mutating-verb list above, so it needs its own entry. | Each invocation MUST be reviewed to confirm the target workflow and inputs. |
| `Skill(update-config*)` | Any invocation of the `update-config` skill: bare `Skill(update-config)`, namespaced `Skill(update-config:<arg>)`, or any future sub-invocation. | The skill writes `.claude/settings.json` / `.claude/settings.local.json`, which is the source of truth for the permission model itself: allow/ask/deny rules, sandbox scope, env vars, and hook commands that run on every tool event. Auto-allowing it creates a privilege-escalation path where the agent can grant itself arbitrary new `allow` entries, install hooks that run arbitrary shell, or widen `sandbox.filesystem.allowWrite` / shrink `denyRead`, all without ever prompting. Sandbox write-scope does not stop this because `.` is in `allowWrite`. A single wildcard entry (`update-config*`) covers every current and future invocation shape in one rule. | Each settings change MUST be reviewed before it lands. Approval here is equivalent in blast radius to approving a `deny`-rule edit: the next tool call may run under new rules. Operators SHOULD diff the proposed change against the live file before approving and SHOULD decline any change that widens `allowWrite`, removes a `deny` entry, adds a broad `allow` wildcard, or registers a hook command. |

## Deny Rules 🚫

These operations are unconditionally blocked, regardless of any `allow` entry or sandbox state. They cover destructive patterns whose blast radius is unacceptable even inside the sandbox (`.` is `allowWrite`, so `rm -rf .` would still erase the working tree and `.git/`).

| Permission | Reason |
|---|---|
| `for *` / `while *` / `until *` | Shell control-flow loops (`for f in ...; do ...; done`, `while read ...`, `until cond; do ...`). See Assumption 8 in [security.md](security.md) for why loops are banned at the policy layer rather than in the textual [AGENTS.md](../../../../../AGENTS.md) rule alone. The sandbox auto-allow heuristic does not recognise loop keywords, so this deny has no cost versus any alternative (allow would also require explicit entries; ask would deadlock). |
| `gh api * -X DELETE *` / `gh api * --method DELETE *` | DELETE is irreversible from the API surface: deleting a release, branch ref, deploy key, or webhook destroys data with no undo. Both `-X` and `--method` spellings are blocked so neither shorthand slips through. |
| `gh api * -X PUT *` / `gh api * --method PUT *` | PUT replaces a resource wholesale. On endpoints like branch protection or rulesets, a PUT silently overwrites the entire policy with whatever payload is sent; partial JSON drops every unspecified field. PATCH (the merge variant) still goes through `ask`. |
| `gh api * /actions/secrets*:*` | Touches GitHub Actions secrets: reading metadata, creating, updating, or deleting. Even GETs leak secret names; mutations rotate credentials CI depends on. Out-of-band secret management only. |
| `gh api repos/*/actions/variables*:*` | Touches Actions variables. Variables are unencrypted secrets-lite: workflows read them like secrets, and they are equally load-bearing for CI. Out-of-band variable management only. |
| `gh api repos/*/collaborators*:*` | Reads or mutates repository collaborator membership. Mutations escalate access; even GETs leak the contributor list. Access changes belong to a human reviewer. |
| `gh api repos/*/keys*:*` | Reads or mutates repository deploy keys. Deploy keys are full-power repo-auth credentials: adding one creates a persistent backdoor; removing one breaks deployments. Manage out-of-band only. |
| `gh api repos/*/pulls/*/merge:*` | Merges a pull request via API, bypassing the `gh pr merge` confirmation flow. Merges are destructive to branch state and trigger downstream CI/deploys. |
| `gh extension *` | Any `gh extension` subcommand. `install` and `upgrade` pull remote code that then runs in-process under the operator's GitHub credentials on every subsequent `gh` invocation; `remove`/`list`/`search`/`exec` are blocked alongside to keep the namespace simple. Extensions belong to a deliberate operator decision, not an agent. |
| `gh gpg-key *` | Any `gh gpg-key` subcommand. `add` installs a persistent commit-signing identity an attacker could use to impersonate the operator on signed commits; `delete` can lock the operator out of signed-commit policies; `list` leaks the key-fingerprint inventory. Out-of-band key management only. |
| `gh issue transfer*` | Moves an issue (with its history and attachments) into a different repository. The destination repo can be attacker-controlled, equivalent to data exfiltration of the issue's contents. Issue transfers must be a deliberate human action. |
| `gh pr merge*` | CLI parallel to the `/pulls/*/merge` API deny. Merges are destructive to branch state and trigger downstream CI/deploys. |
| `gh repo delete*` | Permanently deletes a repository. No undo from the API; recovery requires GitHub support and is not guaranteed. |
| `gh secret *` | Any `gh secret` subcommand. `set`/`remove` mutate CI secrets under the operator's identity; `list` leaks secret names, the exact same risk class as the `gh api * /actions/secrets*` deny ("Even GETs leak secret names"). Out-of-band secret management only. |
| `gh ssh-key *` | Any `gh ssh-key` subcommand. `add` is a persistent auth backdoor giving shell-equivalent push access until revoked; `delete` can lock the operator out; `list` leaks the key-fingerprint inventory. Out-of-band key management only. |
| `gh variable *` | Any `gh variable` subcommand. Mirror of the `gh secret *` rule for Actions variables. Variables are unencrypted secrets-lite; even `list` exposes their values directly, so the entire namespace is blocked and managed out-of-band. |
| `gh workflow disable*` | Disabling a workflow can silently turn off security-critical CI (CodeQL, security-review, lint gates). Must never be done autonomously. |
| `gh workflow enable*` | Re-enabling a workflow can silently restart paused CI (e.g. security scans deliberately disabled during incident response) without operator review. |
| `git -C *` | Running `git` against an arbitrary working tree via the `-C <path>` flag is blocked. The agent has legitimate repositories under `additionalDirectories` (see top of this page) that `-C` could be pointed at, so the sandbox write-boundary alone is not enough to prevent cross-repo edits. Denying the flag forces every git invocation to operate on the repo rooted at the session's current working directory, which the operator set deliberately. Operators who genuinely need to work on a second repo MUST open a new Claude Code session in that directory instead of reaching across with `-C`. |
| `git branch -D*` | Force-deletes local branches regardless of merge status. Can destroy unmerged work with no recovery path. |
| `git clean*` | Any invocation of `git clean` is blocked. All useful variants (`-f`, `-fd`, `-xfd`) force-delete untracked files with no recovery path; the wildcard covers every flag order. Can silently wipe in-progress work the agent has not yet surfaced to the operator. |
| `git commit *--amend*` | Replaces the tip commit instead of adding one. The agent cannot see whether the operator committed on top in the meantime (a release commit, a signed commit), so an amend can rewrite a commit it never authored and detach its tags and signature; on a pushed tip it forces a force-push. Follow-up changes land as a new commit. |
| `git push --force*` | Rewrites remote history. Can permanently destroy other contributors' work. |
| `git reset --hard*` | Discards all uncommitted local changes without any recovery path. |
| `rm -rf*` | Recursive force-delete with no confirmation and no undo. Sandbox `allowWrite` does not protect here because `.` (the repo) is writable; `rm -rf .` would erase the working tree and `.git/`. |
| `sudo*` | Prevents privilege escalation attempts. The sandbox already blocks privileged operations, but denying `sudo` outright avoids accidental approval prompts and makes the intent explicit. |

## Environment Overrides 🌳

The top-level `env` block sets process environment variables for every Claude Code session. It is currently used to disable GPG signing for agent-created commits via the additive `GIT_CONFIG_COUNT` mechanism:

```json
"env": {
  "GIT_CONFIG_COUNT": "1",
  "GIT_CONFIG_KEY_0": "commit.gpgsign",
  "GIT_CONFIG_VALUE_0": "false"
}
```

| Variable | Effect | Why |
|---|---|---|
| `GIT_CONFIG_COUNT` + `GIT_CONFIG_KEY_0` + `GIT_CONFIG_VALUE_0` | Adds `commit.gpgsign=false` on top of the normal git config stack (system → global → local → env). Local `.git/config` and global `~/.gitconfig` are still consulted for everything else (notably `user.name` and `user.email`), so author identity continues to come from the host. | The sandbox `denyRead: ~/.gnupg` rule blocks GPG access by design; agent commands must never touch private key material. This env override removes the resulting signing failure without weakening the credential-path protection. Agent-authored commits land unsigned; the `Co-Authored-By` trailer documents authorship. |

Future env entries SHOULD follow the same principle: prefer adjusting environment over weakening sandbox `denyRead` or extending `allowWrite`.

## Local Overrides 🖥️

Contributors MAY extend project permissions via `.claude/settings.local.json`. This file is git-ignored and applies only to the local machine.

| Rule | Description |
|---|---|
| MUST NOT weaken `deny` | Local overrides cannot lift unconditional blocks defined in `settings.json`. |
| MUST NOT disable the sandbox | Local overrides MUST NOT set `sandbox.enabled: false`, `sandbox.failIfUnavailable: false`, or `sandbox.allowUnsandboxedCommands: true`. The security model depends on the sandbox being on and fail-closed. |
| Machine-specific entries MUST stay local | Absolute paths, process IDs, and debug tooling MUST NOT be promoted to `settings.json`. |
| Shared permissions SHOULD be promoted | Permissions useful for all contributors SHOULD be added to `settings.json` instead of staying local. |
| Keep overrides minimal | Entries already covered by project-level wildcards or by sandbox auto-allow SHOULD be removed from `settings.local.json`. |
