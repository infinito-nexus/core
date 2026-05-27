# CLAUDE.md

## Startup: MUST DO at the Start of Every Conversation 🚀

You MUST read `AGENTS.md` and follow all instructions in it at the start of every conversation before doing anything else.

## Permission State Announcement at Session Start 📢

At the start of every new conversation (after reading `AGENTS.md`), you MUST read [.claude/settings.json](.claude/settings.json) and output a one-time summary: sandbox status with concrete `allowWrite`/`denyRead` paths, plus the counts of `permissions.allow`/`ask`/`deny`. Derive content from the live file; do not hardcode. Do not repeat unless the operator asks, and do not propose `/sandbox` when it is already active.

## Interaction Rules 💬

- A question MUST NOT modify files, code, or state. Only explicit commands MAY.
- You MUST prefer commands permitted in [.claude/settings.json](.claude/settings.json) over commands that require interactive approval when an equivalent exists.

## Code Execution ⚙️

- You MUST prefer `make` targets over raw `docker`/`docker compose`/`ansible-playbook`/`python`/shell invocations whenever an equivalent target exists in the [`Makefile`](Makefile). Inspect the `Makefile` first; fall back to the raw command only when no target covers the operation. The reason is operational consistency, not permissioning. Raw commands also auto-allow under the sandbox.
- You SHOULD run sandbox-confined commands directly on the host. The sandbox bounds what they can read, write, and reach. See [sandbox.md](docs/contributing/tools/agents/claude/sandbox.md).
- For commands that legitimately cannot run inside the sandbox (e.g. operations needing access to `~/.ssh` or `~/.gnupg`), use `make compose-up` to start the stack and `make compose-exec` to drop into a container shell. The repository is mounted at `/opt/src/infinito` (see [compose.yml](compose.yml)), so code changes are immediately available there.
- Commands listed under `permissions.ask` in [.claude/settings.json](.claude/settings.json) still pause for explicit operator confirmation regardless of sandbox state.
- **Shell loops are FORBIDDEN. ⛔** You MUST NOT use `for`, `while`, `until`, or any other shell loop construct in any Bash tool call. Reason: shell control structures fall outside the sandbox auto-allow heuristic and trigger approval prompts even when every subcommand would individually auto-allow.
- **Multi-statement chains in shell invocations are FORBIDDEN. ⛔** You MUST NOT chain independent statements inside a single Bash tool call with **any** statement separator (`;`, literal newline, `&&`, `||`, `&` background operator, or subshell/brace groups around the same). The ban covers causally-dependent chains (`cd X && cmd`) just as much as optional ones, and applies to trailing `&` used to background a command (use the Bash tool's `run_in_background: true` parameter instead). Reason: identical to the loop rule. Split the work across **separate Bash tool calls** or use a single-command equivalent (`xargs`, `grep` with multiple args, a make target).
- **File creation via shell heredoc is FORBIDDEN. ⛔** You MUST NOT use `cat > file <<EOF … EOF` or any variant (`tee > file <<EOF`, `printf "…" > file`, `echo "…" > file` for multi-line content) to create or overwrite files. Use the **Write tool**. For editing an existing file, use **Edit**, not `sed -i`/`awk -i`. Reason: Write/Edit land structured in the transcript and diff; heredoc + redirect shapes also fall out of the auto-allow heuristic and drop into ask.
- **For searching file contents, use the Grep tool.** If shelling out is unavoidable, use a single `grep` invocation with multiple file arguments (e.g. `grep -nE 'pattern' file1 file2 file3`) or a recursive call with a path/glob (e.g. `grep -rnE 'pattern' path/`).
- **When a long-running command streams its output to a `/tmp/<name>.log` file** (e.g. background `make compose-deploy`, `make act-*`, or any `… 2>&1 | tee /tmp/<name>.log`), you MUST tell the operator the concrete `tail -f /tmp/<name>.log` command they can run in another terminal to follow the log live. Include the full path literally so it is copy-pasteable.

## Pushing 🚢

- You MUST NOT push, directly or through wrappers that push implicitly.
- When commits are ready to ship, you MUST instruct the operator to run `git-sign-push` outside the sandbox. The CLI is provided by [git-maintainer-tools](https://github.com/kevinveenbirkenbach/git-maintainer-tools), declared as a dev dependency in [pyproject.toml](pyproject.toml); install it via `make install-python-dev`.

## Configuration 🛠️

- Project-level permissions and sandbox rules are defined in [.claude/settings.json](.claude/settings.json).
- See [code.claude.com](https://code.claude.com/docs/en/settings) for documentation on how to modify it.

## Documentation 📝

See the [Claude Code documentation](https://code.claude.com/docs/en/overview) for further information. For human contributor guidance on working with agents, see [here](docs/contributing/tools/agents/common.md).
