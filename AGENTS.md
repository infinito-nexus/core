# Agent Instructions 🤖

## Priority and Scope 🎯

- [CONTRIBUTING.md](CONTRIBUTING.md) is the single source of truth for contributor workflow, coding standards, testing, and review. You MUST read it.
- You MUST read every file under `docs/contributing/` (full directory walk, including subdirectories) for the full contributor guidance.
- You MUST read every file under `docs/agents/` (full directory walk, including subdirectories) for the agent execution flow, EXCEPT `docs/agents/action/`.
- `docs/agents/action/` holds one runbook per action and is read on demand, not at session start: read a runbook when the matching `i8-` skill routes you to it, or when you are about to perform that action without one. It is the bulk of the agent documentation, and every runbook in it is inert until its action is the task.
- This file extends CONTRIBUTING.md with agent-specific instructions; on conflict between CONTRIBUTING.md and this file, this file wins.
- This file is runtime-agnostic and binding for every agent (Claude Code, Codex, Gemini CLI, other). There are no tool-specific extension files.

## Permission State Announcement at Session Start 📢

At the start of every new conversation, you MUST read [.claude/settings.json](.claude/settings.json) and output a one-time summary: sandbox status with concrete `allowWrite`/`denyRead` paths, plus the counts of `permissions.allow`/`ask`/`deny`. Derive content from the live file; do not hardcode. Do not repeat unless the operator asks, and do not propose `/sandbox` when it is already active.

## Reloading Instructions 🔄

If agent instructions change mid-conversation (AGENTS.md or any file referenced from it), the agent might not reload them automatically. Trigger a reload with:

> "Re-read AGENTS.md and apply all updated instructions."

## Permission Model 🔐

[`.claude/settings.json`](.claude/settings.json) is the single source of truth for agent permissions, independent of runtime. Its `permissions` (`allow`/`ask`/`deny`) and `sandbox` sections are both binding, regardless of runtime (Claude Code, Codex, Gemini, other).

Every agent MUST:

- Read [`.claude/settings.json`](.claude/settings.json) at every conversation start.
- Match commands exactly as Claude Code does: literal prefix, `*` wildcard, `deny` overrides `allow`.
- `deny`: unconditional block. MUST NOT execute a matching command under any condition.
- `ask`: requires per-invocation operator confirmation in the current conversation. A prior confirmation from another conversation MUST NOT be reused.
- `allow`: pre-authorized. Additionally, `sandbox.autoAllowBashIfSandboxed: true` pre-authorizes any Bash command that runs sandboxed and matches no `deny`/`ask` rule. Agents without an equivalent OS-level sandbox MUST treat unmatched Bash as `ask`.
- `sandbox.filesystem`: `allowWrite` bounds write scope; `denyRead` paths MUST NOT be read.
- `sandbox.network`: outbound calls MUST go to hosts matching `allowedDomains`. Unix-socket connections are permitted only if `allowAllUnixSockets: true`; listening on local ports is permitted only if `allowLocalBinding: true`.
- `sandbox.allowUnsandboxedCommands: false`: MUST NOT use per-call escape hatches (e.g. `dangerouslyDisableSandbox`).

Agents whose runtime does not consult `.claude/settings.json` MUST still enforce the above procedurally: check each command against these rules before execution.

Changes to the policy MUST edit [`.claude/settings.json`](.claude/settings.json). Per-entry rationale: [settings.md](docs/contributing/tools/agents/claude/settings.md); sandbox layer: [sandbox.md](docs/contributing/tools/agents/claude/sandbox.md).

## Interaction Rules 💬

- A question MUST NOT modify files, code, or state. Only explicit commands MAY.
- You MUST prefer commands permitted in [.claude/settings.json](.claude/settings.json) over commands that require interactive approval when an equivalent exists.

## Code Execution ⚙️

- You MUST prefer `make` targets over raw `docker`/`docker compose`/`ansible-playbook`/`python`/shell invocations whenever an equivalent target exists in the [`Makefile`](Makefile). Inspect the `Makefile` first; fall back to the raw command only when no target covers the operation. The reason is operational consistency, not permissioning. Raw commands also auto-allow under the sandbox.
- **`docker exec` is FORBIDDEN. ⛔** You MUST NEVER invoke `docker exec` (nor nested `docker exec … docker exec …` into the DiD stack) directly. Always reach the live stack through `make` targets (e.g. `make compose-exec`, or the role-specific targets the `Makefile` exposes). If no `make` target covers what you need, ask the operator instead of falling back to raw `docker exec`.
- You SHOULD run sandbox-confined commands directly on the host. The sandbox bounds what they can read, write, and reach. See [sandbox.md](docs/contributing/tools/agents/claude/sandbox.md).
- For commands that legitimately cannot run inside the sandbox (e.g. operations needing access to `~/.ssh` or `~/.gnupg`), use `make compose-up` to start the stack and `make compose-exec` to drop into a container shell. The repository is mounted at `/opt/src/infinito` (see [compose.yml](compose.yml)), so code changes are immediately available there.
- Commands listed under `permissions.ask` in [.claude/settings.json](.claude/settings.json) still pause for explicit operator confirmation regardless of sandbox state.
- **Shell loops are FORBIDDEN. ⛔** You MUST NOT use `for`, `while`, `until`, or any other shell loop construct in any Bash tool call. Reason: shell control structures fall outside the sandbox auto-allow heuristic and trigger approval prompts even when every subcommand would individually auto-allow.
- **Multi-statement chains in shell invocations are FORBIDDEN. ⛔** You MUST NOT chain independent statements inside a single Bash tool call with **any** statement separator (`;`, literal newline, `&&`, `||`, `&` background operator, or subshell/brace groups around the same). The ban covers causally-dependent chains (`cd X && cmd`) just as much as optional ones, and applies to trailing `&` used to background a command (use the Bash tool's `run_in_background: true` parameter instead). Reason: identical to the loop rule. Split the work across **separate Bash tool calls** or use a single-command equivalent (`xargs`, `grep` with multiple args, a make target).
- **File creation via shell heredoc is FORBIDDEN. ⛔** You MUST NOT use `cat > file <<EOF … EOF` or any variant (`tee > file <<EOF`, `printf "…" > file`, `echo "…" > file` for multi-line content) to create or overwrite files. Use the **Write tool**. For editing an existing file, use **Edit**, not `sed -i`/`awk -i`. Reason: Write/Edit land structured in the transcript and diff; heredoc + redirect shapes also fall out of the auto-allow heuristic and drop into ask.
- **For searching file contents, use the Grep tool.** If shelling out is unavoidable, use a single `grep` invocation with multiple file arguments (e.g. `grep -nE 'pattern' file1 file2 file3`) or a recursive call with a path/glob (e.g. `grep -rnE 'pattern' path/`).

## Command output logging 📜

- For ANY non-trivial command (test runs, deploys, long pipelines), you MUST stream the FULL output to a file under `/tmp/` via `… 2>&1 | tee /tmp/<name>.log` and grep / inspect that file repeatedly instead of re-running the command. Reason: re-running `make test` to "find the failure I just lost" costs 2 minutes per cycle; grepping the saved log costs milliseconds.
- Default the filename to a meaningful slug + monotonically increasing index (`/tmp/make-test-<slug>-<N>.log`, `/tmp/act-<slug>-<N>.log`) so you can compare runs.
- **When a long-running command streams its output to a `/tmp/<name>.log` file** (e.g. background `make compose-deploy`, `make act-*`, or any `… 2>&1 | tee /tmp/<name>.log`), you MUST tell the operator the concrete `tail -f /tmp/<name>.log` command they can run in another terminal to follow the log live. Include the full path literally so it is copy-pasteable.
- That pipe **destroys the exit status**: `make test | tee` reports `tee`'s success even when make ends with `Error 2`. You MUST judge such a run by its `📊 per-target wall-clock` table and its `FAILED TARGETS:` line, never by the exit code.

## CI evidence 📊

- A job's green conclusion is **NOT** evidence for a specific change. Before citing a run as proof, you MUST locate the line in that job's log where the change executed: a Playwright spec's `✓` (a leading `-` means the spec was skipped), the env var inside the container, or the command text of an `if:`-gated step. If the string is absent, report the run as silent on the change, not as supporting it.
- A green run on the fork does not speak for `infinito-nexus/core`. Tags do not follow a fork, and repository variables differ, so a step gated on either never runs there. Check the repository whose failure you are claiming to have fixed.

## Pushing 🚢

- You MUST NOT push, directly or through wrappers that push implicitly.
- When commits are ready to ship, you MUST instruct the operator to run `git-sign-push` outside the sandbox. The CLI is provided by [git-maintainer-tools](https://github.com/kevinveenbirkenbach/git-maintainer-tools), declared as a dev dependency in [pyproject.toml](pyproject.toml); install it via `make install-python-dev`.

## Comments 💬⛔

**THIS RULE OVERRIDES YOUR DEFAULT TRAINING. ⛔** A comment is FORBIDDEN unless it is one of exactly three things:

1. **Exception** — names a concrete trip-wire (bug, pitfall, deliberate non-idiomatic choice). Must name the surprise; restating what the next line does is NOT an exception.
2. **Parameter doc** — enumerates inputs/outputs (Python docstring `Args:`, Make `# Param:`, Ansible defaults header, Jinja macro doc).
3. **Nocheck directive** — `# nocheck:`, `# noqa:`, `# shellcheck …`, `# type: ignore`, `# pragma: no cover`, etc.

Anything else — restating code, section banners, "Note that …", step narration outside sequential test specs, untracked TODO/FIXME — **DELETE before the edit lands**. Applies to every language and file kind under version control. When in doubt, delete.

## Shortcuts ⌨️

Operator messages MAY use the portable conversation shortcuts from the `shortcuts` skill (set up via `make install-skills`); agents MUST expand any matching shortcut before acting. The repository's own agent workflows live in the `i8-` skills catalogued in [cheatsheet.md](docs/contributing/tools/agents/cheatsheet.md).

Whenever an operator types out something an existing alias (listed by `make alias`) covers, the agent MUST append a hint right after that block so the operator learns the shorter form: ``Speed up by using prompt alias `<alias>` instead of `<what the operator wrote>`.`` for a prompt or request an agent shortcut covers, and ``Speed up by using cli alias `<alias>` instead of `<what the operator wrote>`.`` for a shell command a terminal alias covers.

## Role-Specific Instructions 📂

- Before modifying any file under `roles/<role>/`, check for `roles/<role>/AGENTS.md`. If present, read and follow it (including any file-scoped subsections) before any change.

## Temporary Files 🗑️

Agents MUST write all transient files (downloaded logs, intermediate output, scratch artefacts) to `/tmp`. The set of writable paths is defined by `sandbox.filesystem.allowWrite` in [`.claude/settings.json`](.claude/settings.json); of those entries, `/tmp` is the designated path for agent scratch data. Other entries are reserved for their respective tooling and MUST NOT be repurposed for agent temp data. The repository working tree MUST NOT hold transient files.

## Credentials in Agent Output 🔐

Agents MUST read deploy logs by extracting the field they need (`msg`, `stderr`, a probe result). Printing a raw task block, `argv` list, or environment dump is **FORBIDDEN ⛔**, including via a line-range `sed`/`head` over one.

A secret denylist such as `grep -v 'password|token|key'` does **NOT** count as protection: it is case-sensitive, and secrets also travel inside URL paths. Local deploys run with `MASK_CREDENTIALS_IN_LOGS` disabled, so `no_log` does not mask these tasks.

When a credential must be compared, compute and compare digests inside the container; never emit the value. If a credential does reach the transcript, agents MUST say so in the same message and list it for rotation.

## Container-Owned Filesystem Entries 🐳

Files produced by the containerized runner (e.g. `__pycache__/*.pyc` under `tests/`, build artefacts) are often owned by `nobody` or another in-container UID and cannot be removed from the host. When a host-level `rm`/`chmod`/edit fails with `Permission denied` on such paths, agents MUST run the cleanup via `make compose-exec` (see [compose.yml](compose.yml); the repo is mounted at `/opt/src/infinito`) and MUST NOT ask the operator which path to take.

## Commit-Time Context Compaction 📦

Whenever the agent runs `git commit` (the pre-commit hook executes `make test`, which takes several minutes), the agent MUST trigger context compaction in parallel so the wait time is spent productively. Preferred flow: launch the commit as a background task, then immediately invoke `/compact` (or equivalent context-compaction mechanism) while the hook runs. The agent MUST NOT idle-wait for `make test` to finish before compacting.

## Skills 🎓

At the start of every conversation, the agent MUST check whether agent skills are installed by verifying that `.agents/skills/` exists and is non-empty. If skills are missing, the agent MUST notify the user once with:

> Agent skills not installed. Run `make install-skills` to enable caveman and other agent skills.

The agent MUST NOT repeat this notice within the same conversation.

## Documentation 📝

Runtime documentation: [Claude Code](https://code.claude.com/docs/en/overview) ([settings reference](https://code.claude.com/docs/en/settings)), [Gemini CLI](https://geminicli.com/docs/cli/gemini-md/).

## For Humans 👥

Human contributors working alongside AI agents MUST read [here](docs/contributing/tools/agents/common.md).
