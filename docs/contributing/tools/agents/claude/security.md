# Claude Code Security Assumptions 🛡️

This page enumerates the trust assumptions that the Claude Code configuration in [`.claude/settings.json`](../../../../../.claude/settings.json) relies on. If any assumption becomes false on a given host, the corresponding rule in [settings.md](settings.md) or [sandbox.md](sandbox.md) MUST be re-evaluated before Claude Code is started. This file is the single reference for the architectural reasoning. Per-rule tables in the neighbouring pages summarise the mechanics and link here for the full argument.

For the rule catalog itself, see [settings.md](settings.md). For the OS-level sandbox configuration, see [sandbox.md](sandbox.md). For general agent workflow rules shared across all agents, see [common.md](../common.md).

## Two-Layer Containment 🏗️

Claude Code safety rests on two layers.

The **OS-level sandbox** (`sandbox.*` block) is the primary containment. Every Bash command runs inside `bwrap` on Linux or `sandbox-exec` on macOS and is confined by filesystem and network rules. The sandbox itself bounds the blast radius of Bash rather than a per-command allowlist.

The **permission lists** (`permissions.{allow,ask,deny}`) are the policy gate that decides whether the agent may attempt a tool call at all. The `allow` list covers non-Bash tools plus the wildcard `Bash(*)`, delegating real gating to `ask` and `deny`. The `deny` list applies as an unconditional hard block. The `ask` list pauses for operator confirmation.

The split means contributors do not need to extend the allowlist for every new shell command: `Bash(*)` already covers them, and sandbox confinement bounds the blast radius. The `deny` list catches the small set of operations whose blast radius is destructive even within the sandbox. For example, `rm -rf .` would still erase the working tree and `.git/` because `.` is writable under `allowWrite`, so the `rm -rf*` deny rule closes that gap.

## Assumption 1: The sandbox backend is installed and functional ⚙️

The Bash auto-allow path trusts the OS sandbox to confine commands. A missing or broken sandbox backend would cause auto-allow to approve unconfined commands.

**Mitigation:** `sandbox.enabled: true` with `sandbox.failIfUnavailable: true` refuses to start when the backend is unavailable. `sandbox.allowUnsandboxedCommands: false` rejects the `dangerouslyDisableSandbox: true` tool parameter, so there is no per-call escape.

**If violated:** Every Bash command runs unconfined on the host. Contributors MUST install the sandbox backend rather than weaken these flags. See the installer section in [sandbox.md](sandbox.md).

## Assumption 2: `sandbox.filesystem.allowWrite` is the authoritative write boundary ✍️

Path-scoped write restrictions inside `permissions.allow` entries (for example a hypothetical `Bash(tee /tmp/*)` rather than `Bash(*)`) add no security on top of the sandbox. The sandbox enforces write scope at the syscall layer, so any path outside `allowWrite` fails with `EROFS`.

**Enabled by this:** The allow list uses the broad wildcard `Bash(*)` without maintaining narrow path lists. The single source of truth for writable paths is `sandbox.filesystem.allowWrite` in [sandbox.md](sandbox.md).

**If violated:** If a contributor widens `allowWrite` (for example by adding `~/` or `/`), the broad allow rules become genuinely broad. Changes to `allowWrite` SHOULD be reviewed with the same scrutiny as a `deny` rule.

## Assumption 3: The host runs only test workloads 🧪

The `Bash(*)` allow grants broad access to the `docker` CLI (alongside every other shell command) under the assumption that no production containers share the host. Non-mutating-image subcommands (`rm`, `kill`, `stop`, `system prune`, `volume rm`, `cp`) can disrupt or destroy container state. Under test-only usage, the blast radius is bounded to ephemeral state that can be recreated from the compose stack.

**Mitigation:** Image-level mutation (`run`, `build`, `push`, `login`) and their synonyms (`docker container run`, `docker image build`, `docker buildx build`, `docker image push`) still route through `ask`, so the operator reviews them before they execute.

**If violated:** Running Claude Code on a host with production containers exposes those containers to disruption. A contributor on such a host SHOULD add read-only-narrowing `docker *` ask/deny entries in `.claude/settings.local.json` before starting a session.

## Assumption 4: Operators review `ask` prompts before approval 👀

Every rule in `permissions.ask` assumes the operator reads the prompt and confirms the action matches intent. Rules in `ask` are NOT a hard barrier. They are a speed-bump that converts automatic execution into a deliberate decision.

**Protected by this:** `git commit*`, `git push*`, `docker run*`, `docker build*`, `docker push*`, `docker login*`, every mutating `gh` verb, and every non-GET `gh api` call. Each would be destructive or externally visible if executed without review.

**If violated:** Blind-approving `ask` prompts defeats the policy layer entirely. Operators MUST treat every `ask` prompt as a code-review checkpoint.

## Assumption 5: DinD ask-gates are comfort thresholds, not hard barriers 🐳

The `ask` rules on `docker run*` / `docker build*` / `docker push*` / `docker login*` only catch the outermost invocation. Because the project uses Docker-in-Docker (for example `docker exec <helper-container> docker run ...`), a `docker run` invoked inside an exec'd helper container bypasses the ask-gate. The helper container has its own Docker daemon or a bind-mounted host socket, so the inner `docker run` executes directly.

**What this means:** The ask-gate on image-level mutation is a convenience for the common case, not a guarantee.

**If violated:** An invocation of `docker exec <container> docker run --privileged -v /:/host ...` escapes the sandbox without triggering the ask-gate. There is no automated mitigation for this path. Protection relies on the shell-loop deny rule, the `sudo*` deny rule, and operator review of any command that contains nested `docker`.

## Assumption 6: Access to `/var/run/docker.sock` equals host root 🔓

The sandbox has `sandbox.network.allowAllUnixSockets: true` so that normal workflow tools (`docker`, `systemctl`, language servers) continue to work. Any command that reaches `/var/run/docker.sock` can request a container with `-v /:/host --privileged`, which the Docker daemon executes as root and mounts the host filesystem. The sandbox's `allowWrite` does NOT protect against this path because Docker is a trusted service on the other end of the socket.

**Mitigation:** `docker run*` and its synonyms are in `ask`, so the operator reviews them (subject to Assumption 5). The `deny` list blocks `sudo*`, so direct privilege escalation via `sudo` is unavailable.

**If violated:** This is the baseline cost of allowing Docker at all. Contributors on hosts where this cost is unacceptable SHOULD disable Docker socket access locally by denying `/var/run/docker.sock` in `.claude/settings.local.json`, accepting that `docker` commands will stop working.

## Assumption 7: The `Makefile` is peer-reviewed and trusted 🔧

The `Bash(*)` allow lets the agent run any Makefile target without prompting. The `Makefile` is checked into git and reviewed on every pull request, so targets themselves are trusted. Every action a target performs still runs inside the sandbox.

**Mitigation:** Targets still cannot bypass `allowWrite`, `allowedDomains`, or the `deny` list. A malicious target that called `rm -rf .` would be stopped by the `rm -rf*` deny rule.

**If violated:** A compromised `Makefile` could chain multiple non-blocked destructive calls. The mitigation is the normal code-review process for pull requests.

## Assumption 8: Shell control-flow loops are never necessary 🔁

[AGENTS.md](../../../../../AGENTS.md) forbids `for` / `while` / `until` loops in Bash invocations, and `Bash(for *)` / `Bash(while *)` / `Bash(until *)` are in `deny` to enforce the rule. Every task has a flat-form equivalent: a single `grep` with multiple file arguments, `xargs`, a recursive glob, or a dedicated tool.

**Why this matters:** Loops can hide destructive operations (for example `for f in $(ls); do rm "$f"; done`) behind a single approval step. The deny rule converts a rule violation into a hard failure, so the agent receives concrete feedback and refactors to the flat form.

**If violated:** The attempt fails, the agent sees the error, and typically refactors within one retry. No host-level exposure.

## Assumption 9: `denyRead` lists every credential directory 🔐

The sandbox's `denyRead` list (`~/.gnupg`, `~/.kube`, `~/.aws`, `~/.config/gcloud`) is the primary mechanism that prevents the agent from reading host credentials. Every credential store an operator uses on the host is assumed to be covered, **with the documented exception of `~/.ssh`** (see Assumption 10).

**If violated:** A credential directory not listed in `denyRead` (for example `~/.azure`, `~/.doctl`, `~/.config/op`) is readable by the agent, and its contents can leak into the transcript. Contributors adding a new credential store MUST extend `denyRead` in the same commit.

## Assumption 10: `~/.ssh` is intentionally readable to allow `git push` on `ask` 🔑

`git push`, `git fetch`, and `git clone` over SSH all require `ssh(1)` to read `~/.ssh/` (private keys, `known_hosts`, `config`). With `~/.ssh` in `denyRead`, `ssh` fails with `Host key verification failed` / `Could not read from remote repository`, which makes the `ask`-gated `Bash(git push*)` rule unreachable in practice.

The chosen trade-off is to keep `~/.ssh` **out** of `denyRead` so that SSH auth works and `Bash(git push*)` in `ask` becomes the effective control point: every push pauses for operator confirmation. `allowUnsandboxedCommands: false` remains in place, so there is no per-call sandbox bypass.

**Cost:** The agent has read access to all files under `~/.ssh/`, including private keys. A compromised or prompt-injected agent could load those keys into the transcript via read tools (which are NOT gated by `ask`). Mitigations relied upon:

- Private keys SHOULD be passphrase-protected, so exfiltration yields an encrypted blob rather than a usable key.
- Operators MUST treat any unexplained read of `~/.ssh/id_*` in the transcript as a trust incident and rotate the affected keys.
- Hosts that store credentials to high-blast-radius targets (production servers, infrastructure root) SHOULD NOT rely on this assumption; instead use an SSH-agent socket with `~/.ssh` left denied, or switch the git remote to HTTPS plus a narrowly-scoped token.

**If violated (i.e. the cost turns out to be unacceptable on a given host):** Re-add `~/.ssh` to `denyRead` in `.claude/settings.local.json` and handle git pushes from an external terminal, or adopt the SSH-agent-socket variant. Both options preserve the deny without breaking the global policy.

## Updating Assumptions 🧹

When adding a rule to [settings.md](settings.md) or [sandbox.md](sandbox.md) that relies on a novel trust premise, add a numbered assumption here rather than duplicating the reasoning in the rule's rationale column. Per-rule rationales SHOULD stay short (one to two sentences) and link back to this page for the full argument.
