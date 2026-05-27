# Agent Instructions 🤖

## Priority and Scope 🎯

- [CONTRIBUTING.md](CONTRIBUTING.md) is the single source of truth for contributor workflow, coding standards, testing, and review. You MUST read it.
- You MUST read every file under `docs/contributing/` (full directory walk, including subdirectories) for the full contributor guidance.
- You MUST read every file under `docs/agents/` (full directory walk, including subdirectories) for the agent execution flow.
- This file extends CONTRIBUTING.md with agent-specific instructions; on conflict between CONTRIBUTING.md and this file, this file wins.

## Tool-Specific Extensions 🧩

At the start of every conversation, the agent MUST load its matching extension file in addition to AGENTS.md:

- Claude Code → [CLAUDE.md](CLAUDE.md)
- Gemini CLI → [GEMINI.md](GEMINI.md)

Agents MUST NOT read another tool's extension file. On conflict between AGENTS.md and the agent's own tool-specific extension file, the tool-specific file wins.

## Reloading Instructions 🔄

If agent instructions change mid-conversation (AGENTS.md, the tool-specific extension file, or any file referenced from them), the agent might not reload them automatically. Trigger a reload with:

> "Re-read AGENTS.md and the tool-specific extension file (CLAUDE.md or GEMINI.md) and apply all updated instructions."

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

## Role-Specific Instructions 📂

- Before modifying any file under `roles/<role>/`, check for `roles/<role>/AGENTS.md`. If present, read and follow it (including any file-scoped subsections) before any change.

## Temporary Files 🗑️

Agents MUST write all transient files (downloaded logs, intermediate output, scratch artefacts) to `/tmp`. The set of writable paths is defined by `sandbox.filesystem.allowWrite` in [`.claude/settings.json`](.claude/settings.json); of those entries, `/tmp` is the designated path for agent scratch data. Other entries are reserved for their respective tooling and MUST NOT be repurposed for agent temp data. The repository working tree MUST NOT hold transient files.

## Container-Owned Filesystem Entries 🐳

Files produced by the containerized runner (e.g. `__pycache__/*.pyc` under `tests/`, build artefacts) are often owned by `nobody` or another in-container UID and cannot be removed from the host. When a host-level `rm`/`chmod`/edit fails with `Permission denied` on such paths, agents MUST run the cleanup via `make compose-exec` (see [compose.yml](compose.yml); the repo is mounted at `/opt/src/infinito`) and MUST NOT ask the operator which path to take.

## Commit-Time Context Compaction 📦

Whenever the agent runs `git commit` (the pre-commit hook executes `make test`, which takes several minutes), the agent MUST trigger context compaction in parallel so the wait time is spent productively. Preferred flow: launch the commit as a background task, then immediately invoke `/compact` (or equivalent context-compaction mechanism) while the hook runs. The agent MUST NOT idle-wait for `make test` to finish before compacting.

## Skills 🎓

At the start of every conversation, the agent MUST check whether agent skills are installed by verifying that `.agents/skills/` exists and is non-empty. If skills are missing, the agent MUST notify the user once with:

> Agent skills not installed. Run `make install-skills` to enable caveman and other agent skills.

The agent MUST NOT repeat this notice within the same conversation.

## For Humans 👥

Human contributors working alongside AI agents MUST read [here](docs/contributing/tools/agents/common.md).
