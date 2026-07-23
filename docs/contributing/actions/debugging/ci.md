# CI Failures and Debugging 🐛

If CI fails, follow a clean debugging workflow:

1. Download every failed job's logs and artefacts with the tooling below.
2. Inspect the raw logs to find each root failure, then cluster the failures that share a cause.
3. Decide whether each failure belongs to your branch or to something unrelated.
4. Fix related failures in the same branch.
5. Open an issue for unrelated failures instead of mixing them into your branch.

## Fetching and Clustering 📥

The CLI under [cli/meta/ci/logs](../../../../cli/meta/ci/logs/README.md) pulls a run's job logs and artefacts in one shot and clusters them by root failure.

```sh
# All failed jobs' logs + artefacts into /tmp/logs/<run-id>/ (logs/, artifacts/, jobs.json, summary.tsv)
python -m cli.meta.ci.logs.download <run-url> -f

# Group the downloaded logs by their shared failing task, largest cluster first
python -m cli.meta.ci.logs.analyze /tmp/logs/<run-id>
```

`download` accepts conclusion filters (`-s` success, `-f` failed, `-c` cancelled, `-k` skipped; none fetches all), `-d` for the destination, and `-j` for the worker count.
The per-job logs carry the real failing task and its error, and the artefacts carry the Playwright `error-context.md`, screenshots, and `playwright-junit.xml`.

## Important 🚨

- You MUST NOT debug from screenshots alone. Use raw logs.
- You MUST NOT commit log files to the repository.
- If a [Playwright](https://playwright.dev/) job fails, you MUST also download the Playwright assets, store them in `/tmp/`, and analyze them together with the logs.

## Manual CI Jobs 🎯

You SHOULD use targeted manual CI jobs instead of rerunning the full pipeline if you only need one focused check.

Prefer the manual workflow in [entry-manual.yml](../../../../.github/workflows/entry-manual.yml):

- Select your branch.
- Use `debian` unless you have a clear reason to use a different distro.
- Limit the run to the affected app when possible.

This gives faster feedback and protects shared CI runners.

More information [here](https://hub.infinito.nexus/t/infinito-nexus-ci-cd-debugging-guide/462).

## Reproducing Runner Resource Limits Locally 💾

Some CI failures (most notably OOM-kills such as [#162](https://github.com/infinito-nexus/core/issues/162), PeerTube plugin install with `rc=137`) only surface under the memory and CPU ceiling of the GitHub-hosted runner and cannot be reproduced on a workstation with plenty of RAM. To reproduce these failures locally, you MUST cap the resources of the top-level `infinito` service in [compose.yml](../../../../compose.yml) to values that match (or undercut) the runner specs below.

### GitHub-Hosted Runner Specs

All [workflows](../../../../.github/workflows/) target `runs-on: ubuntu-latest`, which maps to the GitHub-hosted standard Linux runner. The effective ceiling depends on the repository's visibility and plan:

| Repository / plan                        | vCPU | RAM    | SSD   |
|------------------------------------------|------|--------|-------|
| Public repo (this repo, `ubuntu-latest`) | 4    | 16 GB  | 14 GB |
| Private repo on Free / Pro / Team        | 2    | 7 GB   | 14 GB |
| Private repo on Enterprise               | 4    | 16 GB  | 14 GB |

The effective budget for the actual workload is lower than the table suggests because the runner itself plus the nested `infinito` container (systemd, nested Docker, Ansible) reserve a non-trivial baseline. Plan for roughly **1–2 GB of overhead** before any role deploys a service.

For the authoritative specs, see the upstream docs for [standard hosted runners](https://docs.github.com/en/actions/using-github-hosted-runners/using-github-hosted-runners/about-github-hosted-runners#standard-github-hosted-runners-for-public-repositories) and [larger runners](https://docs.github.com/en/actions/using-github-hosted-runners/using-larger-runners).

### Env-Var Knobs

[compose.yml](../../../../compose.yml) exposes three env vars on the `infinito` service that cap its memory, swap, and CPU ceiling. For the authoritative variable reference (names, defaults, purpose) see the SPOT in [compose.yml.md](../../artefact/files/compose.yml.md). This page SHOULD NOT duplicate that table and MUST link back to it when a contributor needs the precise definitions.

### Canonical Reproduction Profiles

Pick the profile that matches the runner you want to mimic:

```sh
# Public repo runner (ubuntu-latest, 4 vCPU / 16 GB): the default CI target
INFINITO_MEM_LIMIT=16g INFINITO_MEMSWAP_LIMIT=16g INFINITO_CPUS=4 make <target>

# Private repo runner on Free/Pro/Team (2 vCPU / 7 GB)
INFINITO_MEM_LIMIT=7g INFINITO_MEMSWAP_LIMIT=7g INFINITO_CPUS=2 make <target>

# Aggressive OOM reproducer: forces the memory spike that surfaces #162
INFINITO_MEM_LIMIT=4g INFINITO_MEMSWAP_LIMIT=4g INFINITO_CPUS=2 make <target>
```

Verify the caps applied with `docker compose -f compose.yml config | grep -E 'mem_limit|memswap_limit|cpus'` before starting the deploy.
