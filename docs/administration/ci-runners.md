# CI & Self-Hosted Runners 🏃

How Infinito.Nexus runs its tests, and how to add your own hardware to the CI pool.

## The CI gate

Every push runs the same gate you can run locally:

```bash
make test          # lint + unit + integration + external
```

On GitHub Actions this is followed by the **deploy-test matrix** — real app deploys across Debian/Ubuntu/Arch/Fedora in throwaway containers, with Playwright/CLI end-to-end checks (`.github/workflows/test-deploy-*.yml`). This is the heavy part and the reason self-hosted runners exist.

## Self-hosted runners (opt-in overflow)

By default **all** jobs run on GitHub-hosted runners — no configuration needed. You can add your own machine to run a proportional share of the deploy matrix, controlled by a single repository variable, `CI_SELF_HOSTED_RUNNER_COUNT`:

- `0` / unset → everything GitHub-hosted (default).
- `N` → route a share of deploy jobs to your `[self-hosted, linux]` runners.

### Provision and activate

```bash
# 1. Provision N runner instances on a host (from your control machine)
RUNNER_API_TOKEN=ghp_... make runner-ci-deploy HOST=runner.example.com DISTRO=ubuntu [OWNER=youruser]

# 2. Activate routing (also sets INFINITO_TIMEOUT_MULTIPLIER for slow hardware)
make runner-ci-enable COUNT=2 [OWNER=youruser]

# Kill switch — route everything back to GitHub-hosted
make runner-ci-disable [OWNER=youruser]
```

Full role reference, CLI parameters, and the end-to-end guide: [`roles/svc-runner/README.md`](../../roles/svc-runner/README.md).

## How a runner job is isolated

Each runner instance is provisioned as an ephemeral container using **DooD** (Docker-out-of-Docker — it mounts the host `docker.sock`). Isolation is keyed on the instance number, so parallel jobs never collide:

| Per instance `N` | Value |
|------------------|-------|
| Subnet | `172.30.N.0/24` |
| Compose project | `runner-N` |
| Docker volume dir | `RUNNER_DOCKER_BASE/N` |
| Registration | ephemeral, re-registers per job |

The actual app deploy runs inside a **sealed throwaway Docker daemon** and is torn down on exit, so the host's own stack is never touched. Several runners can share one host (or coexist with other workloads) safely.

## Runtime self-detection

CI behavior is driven by runtime detection, not hand-set flags:

- `RUNTIME` (`dev`/`act`/`github`) selects which test stages run.
- `DOCKER_IN_CONTAINER` (`systemd-detect-virt`) toggles DinD behavior.
- `CI=true` disables the package cache (flaky in nested containers).

## See also

- [Installation Guide](installation.md) — local CLI / dev setup
- [Deploy Guide](deploy.md) — inventory creation and deploys
- [`roles/svc-runner/README.md`](../../roles/svc-runner/README.md) — the runner role in full
