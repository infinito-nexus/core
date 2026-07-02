# GitHub Actions CI Runner

## Description

The [GitHub Actions self-hosted runner](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/about-self-hosted-runners) is an agent that runs GitHub Actions workflow jobs on your own infrastructure instead of GitHub-hosted machines.

## Overview

This role provisions a dedicated machine as one or more GitHub Actions self-hosted CI runners for Infinito.Nexus. Each runner instance runs as an ephemeral Docker container (DooD — Docker out of Docker): the container mounts the host's `/var/run/docker.sock` and uses it to start a fresh Infinito DinD container for each CI job, then tears it down when the job finishes.

Registration tokens are fetched from the GitHub API at container start time via `RUNNER_API_TOKEN` (a GitHub PAT with repo scope). The token is stored in a per-instance `.env` file on disk (mode `0600`, owned by `github-runner`).

The `RUNNER_DISTRIBUTION` variable selects distro-specific package installation tasks (Debian, Ubuntu, Arch Linux, or Fedora/EL). The role is designed to be driven by the `make runner-ci-deploy` target; see the end-to-end guide below.

## Features

- **Self-hosted:** Run CI jobs on your own server without consuming GitHub-hosted runner minutes.
- **Multi-instance:** Provisions N runner instances per host via `RUNNER_COUNT`; each handles one CI job at a time.
- **Ephemeral containers:** Each runner instance is a Docker container (`restart: unless-stopped`). After each job the container re-registers with GitHub as a fresh ephemeral runner (`--ephemeral`).
- **DooD isolation:** Runner containers mount the host Docker socket. Each job gets its own Infinito DinD container with a unique subnet, container names, and Docker volume — parallel jobs never conflict.
- **Automatic registration:** The runner container fetches a short-lived GitHub registration token from the API at startup using `RUNNER_API_TOKEN`.
- **Multi-distro:** Supports Debian, Ubuntu (`apt`), Arch Linux (`pacman`), and Fedora/EL (`dnf`) via distro-specific task files.
- **Idempotent:** Re-running the deploy rebuilds the image and restarts containers cleanly without manual cleanup.
- **CI workflow ready:** All deploy-test workflows route to GitHub-hosted runners by default; set `CI_SELF_HOSTED_RUNNER_COUNT` to overflow jobs to your runners.

## End-to-end guide

### Prerequisites

- A GitHub Personal Access Token (PAT) with `repo` scope, exported as `RUNNER_API_TOKEN` (or `GH_TOKEN`) on the control machine.
- SSH access to the target host (key-based authentication).
- `make install` completed on the control machine (installs Ansible and Python dependencies).

### Step 1 — Provision runner instances on the target server

```bash
RUNNER_API_TOKEN=ghp_... make runner-ci-deploy HOST=runner.example.com DISTRO=ubuntu
```

For a fork, supply your GitHub username so runners register against your repository:

```bash
RUNNER_API_TOKEN=ghp_... make runner-ci-deploy HOST=runner.example.com DISTRO=ubuntu OWNER=youruser
```

Follow the live deploy log in a separate terminal:

```bash
tail -f /tmp/infinito-runner-deploy.log
```

When complete, verify the runners appear in GitHub:

```bash
gh api repos/youruser/infinito-nexus/actions/runners -q '.runners[].name'
```

They should be listed as Idle in `github.com/<owner>/infinito-nexus/settings/actions/runners`.

### Step 2 — Activate self-hosted CI routing

Set the `CI_SELF_HOSTED_RUNNER_COUNT` repository variable so the deploy-test matrix routes overflow jobs to your runners:

```bash
make runner-ci-enable COUNT=2
# or for a fork:
make runner-ci-enable COUNT=2 OWNER=youruser
```

This variable persists until explicitly changed. Confirm it is set at:
`github.com/<owner>/infinito-nexus/settings/variables/actions`

### Step 3 — Push and observe

Push any commit. The runners will pick up jobs routed to `[self-hosted, linux]` once activated.

### Deactivating

To route all CI back to GitHub-hosted runners (e.g. if the server goes down):

```bash
make runner-ci-disable
# or for a fork:
make runner-ci-disable OWNER=youruser
```

## Make targets

| Target | Parameters | Description |
|--------|-----------|-------------|
| `make runner-ci-deploy` | `HOST`, `DISTRO`, `COUNT` (optional), `PORT`, `OWNER`, `REPO` | Provision runner instances on the target host. |
| `make runner-ci-enable` | `COUNT`, `OWNER`, `REPO` | Set `CI_SELF_HOSTED_RUNNER_COUNT` repo variable to activate split routing. |
| `make runner-ci-disable` | `OWNER`, `REPO` | Zero the variable — all CI reverts to GitHub-hosted runners. |

## CLI parameters

The `make runner-ci-deploy` target invokes `python -m cli.deploy.runner`. You can also call it directly:

```bash
python -m cli.deploy.runner <hostname> \
    --distribution <os> \
    --roles svc-runner \
    [--runner-count N] \
    [--owner youruser] \
    [--repo infinito-nexus] \
    [--port 22] \
    [--output /tmp/infinito-runner-deploy.log]
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `hostname` | yes | — | Target server hostname or IP address. |
| `--distribution` | yes | — | OS: `debian`, `ubuntu`, `archlinux`, `fedora`, `centos`. |
| `--roles` | yes | — | Roles to deploy; `svc-runner` is always prepended. |
| `--runner-count` | no | auto (vCPUs ÷ 2) | Number of runner instances to provision. |
| `--owner` | no | role default (`infinito-nexus`) | GitHub user or org the runners register with. |
| `--repo` | no | role default (`core`) | Repository name the runners register with. |
| `--port` | no | Ansible default (22) | SSH port of the target host. |
| `--output` | no | `/tmp/infinito-runner-deploy.log` | File path for deploy stdout/stderr. |

## Role variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RUNNER_GITHUB_OWNER` | `meta/services.yml` | GitHub user or organisation that owns the target repository. |
| `RUNNER_GITHUB_REPO` | `meta/services.yml` | Repository name the runners register with. |
| `RUNNER_API_TOKEN` | `GH_TOKEN` env var | GitHub PAT with repo scope for runner registration. Stored in per-instance `.env` (mode `0600`). |
| `RUNNER_NAME` | `{{ inventory_hostname }}` | Base name; each instance is named `<RUNNER_NAME>-<N>`. |
| `RUNNER_LABELS` | `self-hosted,linux,{{ RUNNER_DISTRIBUTION }}` | Comma-separated labels assigned to every runner instance. |
| `RUNNER_INSTALL_DIR` | `/opt/github-runner` | Base installation directory; instances land in `<dir>/<N>/`. |
| `RUNNER_USER` | `github-runner` | System user account that owns all runner files and processes. |
| `RUNNER_COUNT` | auto (`ansible_processor_vcpus // RUNNER_CPUS`) | Number of runner instances; auto-scales to available CPU cores. |
| `RUNNER_CPUS` | `2` | CPU limit per runner instance (matches GitHub-hosted 2-core quota). |
| `RUNNER_DOCKER_BASE` | `/mnt/docker` | Base path for per-instance Docker volume directories. |
| `RUNNER_PROJECT_PREFIX` | `runner` | Prefix for per-instance Docker Compose project names and `INFINITO_RUNNER_PREFIX`. |
| `RUNNER_SYSCTL_CONF` | `/etc/sysctl.d/99-github-runner.conf` | Path to the sysctl config file written for inotify tuning. |

`RUNNER_DISTRIBUTION` is **required** and has no default; it is passed automatically by the CLI.

## Testing

The role self-validates via the scripts in `files/test/`, discovered and run by `test-e2e-cli` during deploy. `test.sh` orchestrates two complementary checks:

- **`local.sh` — fully local, no external GitHub.** Checks the runner containers are healthy and the DooD socket works, then `container cp`s the repo into a runner, **builds the Infinito image locally**, and deploys `web-app-dashboard` (all other services disabled) inside a **sealed, throwaway Docker daemon** that shares the runner's network namespace. The sandbox is torn down on exit, so the host stack is never touched and **no GitHub/GHCR access is required**. On the async test pass the heavy deploy is skipped (it is validated once on the sync pass).
- **`external.sh` — real job-pickup smoke test (optional).** Uses `RUNNER_API_TOKEN` to confirm the runners registered and are online via the GitHub API, dispatches a smoke workflow, and polls it to completion. Skipped automatically when no token is present.

In short: `local.sh` proves the runner can build and deploy entirely on its own hardware; `external.sh` proves it can receive real jobs from GitHub.

## Further Resources

- [GitHub Actions self-hosted runner documentation](https://docs.github.com/en/actions/hosting-your-own-runners)
- [actions/runner releases](https://github.com/actions/runner/releases)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).

Role contributed by **Alejandro Roman Ibanez** — [GitHub](https://github.com/AlejandroRomanIbanez).
