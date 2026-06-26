# Runner Iteration

Use this page when iterating on the `svc-runner` role or any workflow that involves self-hosted CI runner registration, configuration, or the runner infrastructure itself.
For role-level iteration on other roles, see [Role Loop](role.md).
For workflow-level iteration, see [Workflow Loop](workflow.md).

## Context

`svc-runner` provisions one or more GitHub Actions self-hosted runner instances on a dedicated machine. Each instance is an isolated unit with its own Docker volume, network subnet, and systemd service. The role interacts with the GitHub API (`gh api`) at deploy time to fetch registration tokens — it does **not** store long-lived credentials.

Key facts an agent must hold before acting:

- `RUNNER_GITHUB_OWNER` and `RUNNER_GITHUB_REPO` resolve from `GITHUB_REPOSITORY_OWNER` / `GITHUB_REPOSITORY` env vars when set (CI context), falling back to `meta/services.yml` for production deploys.
- `GH_TOKEN` must be available on the Ansible control node (`delegate_to: localhost`) for the `gh api` registration call to succeed. In CI this is forwarded into the DinD container by `cli/deploy/development/deploy.py`.
- The systemd services installed by `svc.sh` require a host with a real init system. Registration, service install, and service start are skipped when `DOCKER_IN_CONTAINER=true`; the role can be fully deployed in DinD (binary extraction and `.env` file work). The nested `deploy-fresh-purged-apps` call in `test.sh` is also skipped when `DOCKER_IN_CONTAINER=true` — in DinD, `make up` does not start the package-cache proxy (`registry_cache_active()` returns false in CI), so apt inside the fresh container cannot resolve the proxy hostname and package installs fail. Structural checks (binary + `.env`) are sufficient proof of a correct deploy in DinD; the full end-to-end deploy only runs on a real host.
- `runner_count` defaults to `ansible_processor_vcpus // runner_cpus` (auto-scaled to hardware). Override explicitly when debugging a specific count.

## Rules

- You MUST NOT register runners against `infinito-nexus/core` from fork CI — the `GITHUB_TOKEN` there lacks organisation-level `administration` scope. The env-var override in `vars/main.yml` handles this automatically.
- When iterating on the role tasks, deploy to a real Debian, Ubuntu, Arch Linux, or Fedora/EL host, or a systemd-enabled container. Running against the standard DinD test image will fail at the `svc.sh install` step.
- The `test-e2e-cli` framework runs `files/test.sh` sourcing variables from `templates/test.env.j2` after each deploy cycle. Check both the deploy output and the CLI test output before declaring a fix complete.
- When bumping `runner_count`, re-run the full deploy cycle so `test.sh` can run its end-to-end app deploy against the updated runner environment.
- `runner_docker_base` defaults to `/mnt/docker`. Override via inventory `host_vars` for non-standard machines.

## Iteration loop

1. Make the code change.
2. Run `make test` — all linting and unit tests must pass before deploy.
3. Deploy to the target host via the standard role deploy path.
4. Inspect systemd service status: `systemctl is-active actions.runner.*`.
5. Check `files/test.sh` output from the `test-e2e-cli` run in the deploy log.
6. If the runner registered correctly, verify it appears in the GitHub repository's runner list.

## Enabling self-hosted runners in the org

To allow `GITHUB_TOKEN` (with `actions: write`) to register runners on the `infinito-nexus` organisation, a repository admin must enable:

> Settings → Actions → General → "Allow GitHub Actions to manage runners"

Without this setting, runner registration from org CI will fail with HTTP 403. Fork CI is unaffected because the token has full access to the fork repository.
