# GitHub Actions CI Runner

## Description

The [GitHub Actions self-hosted runner](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/about-self-hosted-runners) is an agent that runs GitHub Actions workflow jobs on your own infrastructure instead of GitHub-hosted machines.

## Overview

This role provisions a dedicated machine as one or more GitHub Actions self-hosted CI runners for Infinito.Nexus. It downloads and installs the official runner binary once, then provisions N independent runner instances — each with its own directory, registration token, and systemd service. Registration tokens are fetched from the GitHub API via `gh` on the Ansible control host at deploy time; no long-lived PAT is stored in the inventory.

The `runner_distribution` variable selects distro-specific package installation tasks (Debian, Ubuntu, or Arch Linux). The role is designed to be driven by the `make runner-ci-deploy` target; see the end-to-end guide below.

## Features

- **Self-hosted:** Run CI jobs on your own server without consuming GitHub-hosted runner minutes.
- **Multi-instance:** Provisions N runner instances per host via `runner_count`; each handles one job at a time.
- **Automatic registration:** Fetches a short-lived token via `gh api` on the control host — no long-lived PAT stored anywhere.
- **Systemd service:** Each runner instance is installed as a systemd service that starts on boot.
- **Multi-distro:** Supports Debian, Ubuntu (`apt`) and Arch Linux (`pacman`) via distro-specific task files.
- **Idempotent:** Re-running the deploy re-registers runners in-place (`--replace`) without manual cleanup.
- **CI workflow split:** Deploy-test jobs are proportionally split between GitHub-hosted and self-hosted runners when `CI_SELF_HOSTED_RUNNER_COUNT` is set; forks without the variable are unaffected.

## End-to-end guide

### Prerequisites

- `gh` CLI installed and authenticated on the control machine (`gh auth login`).
- SSH access to the target host (key-based authentication).
- `make install` completed on the control machine (installs Ansible and Python dependencies).

### Step 1 — Provision runner instances on the target server

```bash
make runner-ci-deploy HOST=runner.example.com DISTRO=ubuntu COUNT=15
```

For a fork, supply your GitHub username so runners register against your repository:

```bash
make runner-ci-deploy HOST=runner.example.com DISTRO=ubuntu COUNT=15 OWNER=youruser
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
make runner-ci-enable COUNT=15
# or for a fork:
make runner-ci-enable COUNT=15 OWNER=youruser
```

This variable persists until explicitly changed. Confirm it is set at:
`github.com/<owner>/infinito-nexus/settings/variables/actions`

### Step 3 — Push and observe

Push any commit. In the Actions tab you will see two parallel job sets for each deploy workflow:

| Job | `runs-on` | Apps |
|-----|-----------|------|
| `server` / `universal` / `workstation` | `ubuntu-latest` | proportional share |
| `server-self-hosted` / … | `[self-hosted, linux]` | remaining apps |

Both batches run simultaneously, reducing total pipeline time roughly in half.

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
| `make runner-ci-deploy` | `HOST`, `DISTRO`, `COUNT` (default 15), `PORT`, `OWNER`, `REPO` | Provision runner instances on the target host. |
| `make runner-ci-enable` | `COUNT`, `OWNER`, `REPO` | Set `CI_SELF_HOSTED_RUNNER_COUNT` repo variable to activate split routing. |
| `make runner-ci-disable` | `OWNER`, `REPO` | Zero the variable — all CI reverts to GitHub-hosted runners. |

## CLI parameters

The `make runner-ci-deploy` target invokes `python -m cli.deploy.runner`. You can also call it directly:

```bash
python -m cli.deploy.runner <hostname> \
    --distribution <os> \
    --roles svc-runner \
    [--runner-count 15] \
    [--owner youruser] \
    [--repo infinito-nexus] \
    [--port 22] \
    [--output /tmp/infinito-runner-deploy.log]
```

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `hostname` | yes | — | Target server hostname or IP address. |
| `--distribution` | yes | — | OS: `debian`, `ubuntu`, `archlinux`. |
| `--roles` | yes | — | Roles to deploy; `svc-runner` is always prepended. |
| `--runner-count` | no | `15` | Number of runner instances to provision. |
| `--owner` | no | role default (`kevinveenbirkenbach`) | GitHub user or org the runners register with. |
| `--repo` | no | role default (`infinito-nexus`) | Repository name the runners register with. |
| `--port` | no | Ansible default (22) | SSH port of the target host. |
| `--output` | no | `/tmp/infinito-runner-deploy.log` | File path for deploy stdout/stderr. |

## Role variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RUNNER_GITHUB_OWNER` | `meta/services.yml` | GitHub user or organisation that owns the target repository. |
| `RUNNER_GITHUB_REPO` | `meta/services.yml` | Repository name the runners register with. |
| `runner_name` | `{{ inventory_hostname }}` | Base name; each instance is named `<runner_name>-<N>`. |
| `runner_labels` | `self-hosted,linux,{{ runner_distribution }}` | Comma-separated labels assigned to every runner instance. |
| `runner_install_dir` | `/opt/github-runner` | Base installation directory; instances land in `<dir>/<N>/`. |
| `runner_user` | `github-runner` | System user account that owns and runs all runner processes. |
| `runner_count` | auto (`ansible_processor_vcpus // runner_cpus`) | Number of runner instances; auto-scales to available CPU cores. |
| `runner_cpus` | `2` | CPU limit per runner instance (matches GitHub-hosted 2-core quota). |
| `runner_docker_base` | `/mnt/docker` | Base path for per-instance Docker volume directories. |
| `runner_project_prefix` | `runner` | Prefix for per-instance Docker Compose project names and `INFINITO_RUNNER_PREFIX`. |

`runner_distribution` is **required** and has no default; it is passed automatically by the CLI.

## Further Resources

- [GitHub Actions self-hosted runner documentation](https://docs.github.com/en/actions/hosting-your-own-runners)
- [actions/runner releases](https://github.com/actions/runner/releases)

## Credits

Developed and maintained by **Alejandro Roman Ibanez**.
Learn more at [github.com/AlejandroRomanIbanez](https://github.com/AlejandroRomanIbanez).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
