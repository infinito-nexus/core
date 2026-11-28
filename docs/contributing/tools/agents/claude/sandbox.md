# Claude Code Sandbox 🏖️

This page documents the OS-level sandbox configuration for Claude Code. The relevant keys live under `sandbox` in [`.claude/settings.json`](../../../../../.claude/settings.json). The sandbox is the **primary** containment layer in this project: because the allowlist uses the wildcard `Bash(*)` (with `autoAllowBashIfSandboxed` as defence-in-depth), sandbox confinement, not the per-command allowlist, is what bounds the blast radius of Bash. The `allow`/`ask`/`deny` lists described in [settings.md](settings.md) remain in force on top of it as the policy gate.

## Activation 🟢

The sandbox is activated unconditionally via `"sandbox": { "enabled": true }`. This means filesystem and network restrictions below are enforced **at every session**, not only when the operator manually switches into sandbox permission mode. The OS-level sandbox is the source of truth for what commands may read, write, and reach over the network; the `allow`/`ask`/`deny` permission lists remain in force as a second line of defence for policy concerns the OS cannot express (e.g. requiring confirmation before publishing a commit).

## Fail-Closed on Missing Backend 🔒

The settings file additionally sets `"sandbox": { "failIfUnavailable": true }`. This prevents a dangerous false-security state: if the OS-level sandbox backend (e.g. `bwrap` on Linux, `sandbox-exec` on macOS) is missing or non-functional, Claude Code would otherwise silently fall back to no sandboxing while `autoAllowBashIfSandboxed` continues to auto-approve commands as if they were confined. With `failIfUnavailable: true`, Claude Code refuses to proceed in that situation, forcing the operator to install the missing backend or explicitly downgrade the policy before any command runs. Contributors on systems without a working sandbox backend MUST install the appropriate binary rather than weakening this flag locally.

## No Unsandboxed Escape Hatch 🚪

`"sandbox": { "allowUnsandboxedCommands": false }` removes the operator's ability to opt a single command out of the sandbox. The `dangerouslyDisableSandbox: true` parameter exposed by the Bash tool is rejected when this flag is `false`, so there is no per-call "trust me, run this raw on the host" path. Commands that legitimately cannot run inside the sandbox (e.g. operations requiring access to `~/.ssh` or `~/.gnupg`) MUST be invoked manually by the operator outside Claude Code rather than smuggled through an unsandboxed escape.

## Bash Auto-Allow ⚡

`"sandbox": { "autoAllowBashIfSandboxed": true }` treats sandbox confinement as sufficient policy for Bash. It exists as defence-in-depth alongside the explicit `Bash(*)` allow entry in `permissions.allow`: with either in place, Bash commands run automatically as long as no `deny` or `ask` rule matches. The wildcard `Bash(*)` is the primary gate today; the flag guarantees the agent stays functional if that entry is ever narrowed or removed. This keeps the allowlist small (see [settings.md](settings.md)) and removes the friction of extending it for every new make target or script. The trade-off is that the sandbox MUST be correct: `allowWrite`, `denyRead`, and the network rules below are now the operative policy for what Bash can touch.

## Installing the Sandbox Backend 📥

On Linux, the sandbox backend requires `bubblewrap` (provides the `bwrap` binary) and `socat`. The project ships a cross-distribution installer at [`scripts/install/sandbox.sh`](../../../../../scripts/install/sandbox.sh) that detects the distribution via `/etc/os-release` and installs both packages with the native package manager. Supported distributions:

| Distribution | Package manager | Notes |
|---|---|---|
| Debian, Ubuntu (+ derivatives like Mint, Pop!_OS, Raspbian) | `apt-get` | Uses `--no-install-recommends`. |
| Fedora | `dnf` | |
| CentOS, RHEL, Rocky Linux, AlmaLinux | `dnf` (fallback `yum`) | CentOS/RHEL 7 need EPEL enabled out-of-band. |
| Arch, Manjaro, EndeavourOS | `pacman` | Installs from `extra`. |

Invoke it via the dedicated Make target (preferred, matches the agent permission model in [`.claude/settings.json`](../../../../../.claude/settings.json)):

```bash
make install-agent
```

Equivalent direct invocation:

```bash
bash scripts/install/sandbox.sh
```

Both paths elevate privileges via `sudo` when not run as root, and the script verifies `bwrap` and `socat` on `PATH` before it exits. macOS uses `sandbox-exec` from the base system and does not need this target.

## Write Scope ✍️

The agent MAY write to the paths listed in `sandbox.filesystem.allowWrite`. All other paths are read-only by default.

| Path | Purpose |
|---|---|
| `.` | The repository working tree. Required for any code change. |
| `/tmp` | The **only** location outside the repository where transient agent output (downloaded logs, scratch files, intermediate artefacts) MAY be written; see the *Temporary Files* rule in [`AGENTS.md`](../../../../../AGENTS.md). |
| `~/.cache/pre-commit` | Cache directory used by the [pre-commit](https://pre-commit.com/) framework. Granted because pre-commit hooks run on every commit and need to populate and read this cache; without it, every commit attempt would fail with `Read-only file system`. The cache contains only hook tool installations, no project data. |
| `~/.cache/pip` | pip's package cache. Granted because the project's `make install-python` step (transitively invoked by `make test`, which runs as a pre-commit hook) populates this cache; denying it would force every install to redownload from PyPI even when the requirements have not changed. |
| `~/.cache/gh` | `gh` CLI's cache directory (HTTP response cache + extension metadata). Granted because every `gh` invocation writes cache entries at startup; denying it would require every `gh` call to be wrapped with an `XDG_CACHE_HOME=/tmp/...` env prefix, which adds a shell shape that falls out of sandbox auto-allow and forces per-subcommand allow entries. Auth tokens are **not** stored here (they live in `~/.config/gh/`, which stays read-only). Persistence trade-off is identical to `~/.cache/pip` / `~/.cache/pre-commit`: cache poisoning, if it occurred, would survive reboots, but API auth is server-side so the blast radius is bounded to wrong-output-to-operator. |
| `~/.local/share/worktrees` | Default parent directory of the branch worktrees created by `make worktree-up`. Granted at the `worktrees` level rather than per repository so the target can create the `<domain>/<account>/<repo>` path it derives from `git remote get-url origin`; without it `mkdir -p` fails with `Read-only file system` before any checkout happens. The directory holds only git checkouts of this repository, no host credentials. |
| `~/.local/share/infinito/cache` | Default `INFINITO_CACHE_PIN_ROOT`: the checkouts of the pinned cache commit, the `.lock` that serializes their materialization with `make cache-apply`, and `upstreams.conf`, the map the cache frontend mounts. Required because `make cache-declare`, `make cache-apply` and `make compose-up` extract the pinned commit there with `git archive` and install the map; without it they fail with `Read-only file system` (see [cache.md](../../../environment/cache.md)). The directory holds only exported commits of this repository and their rendered cache files, no host credentials. |
| `~/.local/state/infinito` | Directory of `INFINITO_CACHE_PIN_FILE` (`cache.ref`) and its `cache.applied` record. Granted at the directory level because `make cache-declare` and `make cache-apply` replace both files atomically through a scratch file beside them. It holds two commit ids, no host credentials. |
| `~/.ansible` | Ansible's runtime state directory (notably `~/.ansible/tmp/`, where `ansible-galaxy` and other ansible CLIs create per-invocation temp dirs). Required because the pre-commit `make test` flow runs `make install-ansible`, which fails to even initialize the `ansible` Python package without write access here (`DEFAULT_LOCAL_TMP` setup uses `tempfile.mkdtemp` against this path). |

`~/.venvs` is deliberately not writable: `~/.venvs/pkgmgr/bin` is `PATH[0]` for the operator's shells, so a sandboxed command could plant `git`, `python3`, `bash` or `node` there for unsandboxed hooks and shells to execute; gate runs use `env VENV=` virtualenvs under `~/.local/share/worktrees/.venvs`, which the `~/.local/share/worktrees` entry already covers.

Adding entries here widens the agent's effective write scope. New paths SHOULD be justified against the same standard as the existing three (required for normal workflow, no sensitive content, narrow as possible).

## Read Restrictions 🚫

The following paths are never readable, even if a task explicitly requests access:

| Path | What it protects |
|---|---|
| `~/.gnupg` | GPG keys and keyrings. The agent therefore cannot create signed commits. See the GPG signing override in [settings.md](settings.md#environment-overrides-) for how this is reconciled with `commit.gpgsign=true` on the host. |
| `~/.kube` | Kubernetes cluster credentials. |
| `~/.aws` | AWS access keys and configuration. |
| `~/.config/gcloud` | Google Cloud service account credentials. |
| `~/.docker/config.json` | Registry credentials that `docker login` stores inline. Docker CLI calls inside the sandbox pull anonymously and print `WARNING: Error loading config file` on stderr. |
| `~/.git-credentials` | HTTPS credentials written by git's `store` credential helper. |
| `~/.netrc` | Machine credentials read by `curl`, `git`, and `pip`. |
| `~/.ssh/id_dsa`, `~/.ssh/id_ecdsa`, `~/.ssh/id_ecdsa_sk`, `~/.ssh/id_ed25519`, `~/.ssh/id_ed25519_sk`, `~/.ssh/id_rsa` | The default SSH private keys. |

The rest of `~/.ssh` stays readable, because `ssh` needs `known_hosts` and `config` for `git fetch`; authentication goes through the SSH agent. See [security.md](security.md#assumption-10-ssh-stays-readable-except-for-the-default-private-keys-) (Assumption 10).

## Network 🌐

The `sandbox.network` block governs outbound and local connectivity from inside the sandbox.

| Field | Current value | Effect |
|---|---|---|
| `allowedDomains` | List of domain patterns the agent or its tooling needs to reach. Apex domains are listed bare (`pypi.org`, `github.com`, `ghcr.io`, `letsencrypt.org`, `monogramm.io`, `cybermaster.space`, `infinito.nexus`, `infinito.test`); subdomain families use the `*.parent.tld` form (`*.pythonhosted.org`, `*.ansible.com`, `*.amazonaws.com`, `*.github.com`, `*.githubusercontent.com`, `*.npmjs.org`, `*.docker.com`, `*.gitea.com`, `*.hcaptcha.com`, `*.gstatic.com`, `*.taiga.io`, `*.infinito.nexus`, `*.infinito.test`). | Subdomain wildcards (`*.example.com`) are honored, but a bare `*` is not; sandboxed network access is enforced per pattern, and any unmatched host triggers an interactive `SandboxNetworkAccess` prompt. Add a new pattern here when introducing tooling that fetches from a new origin; egress is still bounded by any host-level firewall on top. |
| `allowAllUnixSockets` | `true` | The sandbox can connect to any Unix-domain socket on the host. Required so commands like `docker`, `systemctl`, and language servers continue to work; these all communicate over Unix sockets (e.g. `/var/run/docker.sock`). |
| `allowLocalBinding` | `true` | The agent MAY bind listening sockets on `localhost` (e.g. `make compose-up`, `python -m http.server`, dev servers). Required for any local end-to-end testing. |

If a contributor needs to tighten network policy locally (e.g. running on an untrusted network), they SHOULD do so via `.claude/settings.local.json` rather than weakening the project-level defaults that other contributors depend on.

## Local Stacks 🧱

Sandboxed make targets reach every local stack through the host Docker socket that `allowAllUnixSockets` opens; the sandbox bounds only the host paths those targets write.

| Stack | Class | Make targets | Host paths it writes |
|---|---|---|---|
| Infra runner `infinito-infra` with the caches and the tools | always-on (caches), on-demand (tools) | `make infra-up`, `make infra-status`, `make cache-status`, `make cache-evict` | `DIR_CACHE` (`/var/cache/infinito/core/cache`, in `allowWrite`): the machine lock, the owner marker and every cache byte |
| Shared test runner `infinito-test-<hash>`, one per toolchain image | long-lived | `make test-unit*`, `make test-integration`, `make test-external`, `make test-lint`, `make test-performance`, `make test-session`, every `make lint*` target and `make autoformat`, and through them `make test`, `make quality` and `make quality-high`; `make test-runner-status` shows it and `make test-runner-down` removes it | its start lock `/tmp/infinito-test-<hash>.lock` |
| Deploy stack of a checkout | on-demand | `make compose-deploy`, `make compose-exec`, `make compose-down`, `make worktree-down` | the checkout |

The job queue of the runner pool lives in `<DIR_CACHE>/jobs` (`/var/cache/infinito/core/cache/jobs`), which `allowWrite` covers through `DIR_CACHE`, so a deploy with `INFINITO_DEPLOY_VIA_POOL=true` submits its job from inside the sandbox once the operator belongs to the `runner-queue` group, and `job=<id>` reaches the held stack through the queue's `docker.sock`, which `allowAllUnixSockets` admits.
With `INFINITO_STACK_NAME` set, the deploy, exec, test and lint targets address that stack instead of the default ones.
