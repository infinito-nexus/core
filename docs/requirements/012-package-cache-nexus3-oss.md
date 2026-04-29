# 012 - Package Cache (Nexus 3 OSS)

## User Story

As a developer running infinito-nexus locally, I want a pull-through
cache for OS, language, and chart packages (apt, pypi, npm, helm, raw,
…) so that re-deploys and fresh-purges do not trigger live upstream
package-manager round-trips, in the same way the existing
[`registry-cache`](../../compose/registry-cache/README.md) already
covers Docker image pulls.

## Dependencies

This requirement is a peer addition to the existing `registry-cache`
service defined in [compose.yml](../../compose.yml) and does NOT modify
or depend on its runtime behaviour. It reuses the same conventions
introduced for `registry-cache`:

- the `cache` compose profile,
- the `Profile` gate in
  [cli/deploy/development/profile.py](../../cli/deploy/development/profile.py),
- the strict `${VAR:?…}` env-var contract documented under the
  Registry Cache section of
  [docs/contributing/artefact/files/compose.yml.md](../contributing/artefact/files/compose.yml.md),
- the per-cache env script under `scripts/meta/env/`, sourced via
  [scripts/meta/env/all.sh](../../scripts/meta/env/all.sh).

The `registry-cache` service MUST remain in place after this
requirement lands. See **Coexistence**.

## Background

Today, only Docker image pulls are cached. The
`rpardini/docker-registry-proxy`-based `registry-cache` transparently
MITMs every outbound image pull from the `infinito` runner's inner
dockerd, regardless of upstream registry (Docker Hub, mcr.microsoft.com,
ghcr.io, gcr.io, quay.io, …).

Package-manager downloads from inside the runner — `apt`, `pip`, `npm`,
`helm`, occasional `curl` against `raw.githubusercontent.com`, etc. —
hit upstream on every deploy. This dominates re-deploy time on slow
links and exposes the dev workflow to upstream outages it could
otherwise ride out.

Format-specific proxies (`devpi`, `verdaccio`, `apt-cacher-ng`,
`pacoloco`, `chartmuseum`) would each cover one slice but multiply the
moving parts. Sonatype **Nexus Repository OSS 3.x** (EPL 1.0) is the
only single-component OSS solution that proxies all relevant formats in
one process.

Nexus 3 OSS is added as a **second** service under the existing `cache`
profile, COMPLEMENTING the registry-cache rather than replacing it.

## Naming

The compose service is named `package-cache` (NOT `nexus`) to avoid
collision with the project name `infinito-nexus`. Container name:
`infinito-package-cache`. Internal hostname inside the compose default
network: `package-cache`.

## Coexistence with `registry-cache`

This requirement explicitly does NOT replace the rpardini-based
registry-cache. Reason: `rpardini/docker-registry-proxy` MITMs every
outbound HTTPS image pull transparently, so `image:` references in
roles work unchanged across all registries. Nexus's `docker-proxy`
repos, in contrast, require client-side rewriting (image refs become
`package-cache:8082/...`) or `registry-mirrors` config that only
covers Docker Hub. Replacing rpardini would either lose multi-registry
transparency or force a sweep over every `image:` field in the tree.

Therefore:

- Docker image pulls continue to flow through `registry-cache`.
- Package downloads (apt/pip/npm/helm/raw) flow through `package-cache`.
- The two services run in parallel, both gated by the `cache` profile.

## Target Layout

### Compose service

A new service in [compose.yml](../../compose.yml), peer to
`registry-cache`:

```yaml
package-cache:
  profiles: ["cache"]
  image: sonatype/nexus3:<pin>          # pin to a specific tag; never :latest
  container_name: infinito-package-cache
  environment:
    INSTALL4J_ADD_VM_PARAMS: "-Xms${INFINITO_PACKAGE_CACHE_HEAP:?…} -Xmx${INFINITO_PACKAGE_CACHE_HEAP:?…} -XX:MaxDirectMemorySize=${INFINITO_PACKAGE_CACHE_DIRECT_MEM:?…}"
  volumes:
    - type: bind
      source: ${INFINITO_PACKAGE_CACHE_HOST_PATH:?Source scripts/meta/env/cache/package.sh before running docker compose}
      target: /nexus-data
      bind:
        create_host_path: true
  healthcheck:
    test:
      - CMD-SHELL
      - "wget -qO- http://127.0.0.1:8081/service/rest/v1/status >/dev/null 2>&1"
    interval: 5s
    timeout: 3s
    retries: 60
    start_period: 120s
  restart: unless-stopped
```

The `infinito` service gains an optional dependency:

```yaml
depends_on:
  package-cache:
    condition: service_healthy
    required: false
```

Same `required: false` pattern as the existing `registry-cache`
dependency: when the `cache` profile is inactive, compose does not pull
the service in, and the runner boots without it.

### Env defaults

A new file `scripts/meta/env/cache/package.sh`, modelled on
[scripts/meta/env/cache/registry.sh](../../scripts/meta/env/cache/registry.sh),
sourced via `scripts/meta/env/all.sh`:

| Variable                              | Default                                                  | Notes                                                                       |
|---------------------------------------|----------------------------------------------------------|-----------------------------------------------------------------------------|
| `INFINITO_PACKAGE_CACHE_HOST_PATH`    | `/var/cache/infinito/core/cache/package/data`                  | Bind target for `/nexus-data`. Created on first start.                      |
| `INFINITO_PACKAGE_CACHE_HEAP`         | derived from free RAM, capped at `2g`, floor `1g`        | JVM heap (`-Xms` / `-Xmx`); Nexus 3 OSS minimum is 1 GiB.                   |
| `INFINITO_PACKAGE_CACHE_DIRECT_MEM`   | derived; floor `1g`                                      | `MaxDirectMemorySize`; per Nexus sizing guide.                              |
| `INFINITO_PACKAGE_CACHE_BLOBSTORE_MAX`| half of free disk space at the cache path, floor `2g`    | Soft cap reflected in the bootstrap helper's blobstore quota.               |
| `INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD` | empty (operator-supplied)                              | First-start bootstrap rotates the auto-generated admin password to this.    |

`compose.yml` MUST consume each of these strictly via
`${VAR:?Source scripts/meta/env/cache/package.sh before running docker compose}`.
Running `docker compose config` without sourcing the env script MUST
fail explicitly with the same shape of error the registry-cache vars
produce today.

### Profile gate

[cli/deploy/development/profile.py](../../cli/deploy/development/profile.py)
already gates the `cache` profile to local-dev (active) vs. CI
(inactive). This requirement does NOT introduce a second toggle:
`package-cache` and `registry-cache` activate together via the existing
`cache` profile.

### Bootstrap of proxy repositories

A new helper `scripts/docker/cache/package.sh`, idempotent,
invoked once on first start of the runner under the `cache` profile
(analog to how
[scripts/docker/cache/registry-ca.sh](../../scripts/docker/cache/registry-ca.sh)
is invoked via `ExecStartPre`):

- Reads the auto-generated admin password from
  `/nexus-data/admin.password` (Nexus writes this on first boot, then
  removes the file once admin password is changed).
- Rotates it to `${INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD}`.
- Creates a single blobstore `default` with quota
  `${INFINITO_PACKAGE_CACHE_BLOBSTORE_MAX}`.
- Creates the MVP set of proxy repositories via
  `POST /service/rest/v1/repositories/{format}/proxy`. 200 (created)
  and 400 / 409 (already exists) are both accepted; any other status
  is fatal.

MVP proxy repos:

| Format     | Repo name              | Upstream                                                  |
|------------|------------------------|-----------------------------------------------------------|
| `apt`      | `apt-debian`           | `http://deb.debian.org/debian` (per supported suite)      |
| `apt`      | `apt-ubuntu`           | `http://archive.ubuntu.com/ubuntu` (per supported suite)  |
| `pypi`     | `pypi-proxy`           | `https://pypi.org/`                                       |
| `npm`      | `npm-proxy`            | `https://registry.npmjs.org/`                             |
| `helm`     | `helm-bitnami`         | `https://charts.bitnami.com/bitnami`                      |
| `raw`      | `raw-githubusercontent`| `https://raw.githubusercontent.com/`                      |

Adding more formats later (yum, go, composer, cargo-via-raw, …) is an
allowlist update in the same helper; out of scope for the MVP.

### Client wiring inside `infinito`

Following the same pattern as
[compose/registry-cache/proxy.conf](../../compose/registry-cache/proxy.conf),
this requirement adds a new directory `compose/package-cache/` that
holds client-config snippets, each bind-mounted read-only into the
runner under the `cache` profile and falling back to `/dev/null` when
the profile is inactive:

| Snippet                            | Mount target inside runner                          | Effect                                                 |
|------------------------------------|------------------------------------------------------|--------------------------------------------------------|
| `compose/package-cache/pip.conf`   | `/etc/pip.conf`                                      | `index-url = http://package-cache:8081/repository/pypi-proxy/simple/` |
| `compose/package-cache/npmrc`      | `/root/.npmrc`                                       | `registry=http://package-cache:8081/repository/npm-proxy/`            |
| `compose/package-cache/apt.list`   | `/etc/apt/sources.list.d/package-cache.list`         | distro-appropriate `deb http://package-cache:8081/repository/apt-…/` |
| `compose/package-cache/helm-init.sh` | invoked once on runner first-start                 | `helm repo add` against the proxy URLs                                |

All binds fall back to `/dev/null` (single env var per file, default
`/dev/null`, set by the `Profile` class when the `cache` profile is
active) so the runner deploys identically with the cache off — no
failed deploys, just direct upstream traffic.

DNS to the hostname `package-cache` works because both containers sit
on the compose `default` network (and CoreDNS, when active in CI,
resolves it equally).

### Compose-yml documentation

`compose/package-cache/README.md` mirrors the shape of
[compose/registry-cache/README.md](../../compose/registry-cache/README.md):
**Activation**, **Scope**, **Files**, and a pointer to the env-var
contract.

[docs/contributing/artefact/files/compose.yml.md](../contributing/artefact/files/compose.yml.md)
gains a Package Cache section beside the existing Registry Cache one.

## Acceptance Criteria

### Service & profile

- [ ] `compose.yml` defines a `package-cache` service with
      `profiles: ["cache"]`, image pinned to a specific
      `sonatype/nexus3:<tag>` (NOT `:latest`), `container_name`
      `infinito-package-cache`.
- [ ] The service exposes a healthcheck that reports healthy once
      Nexus's REST API responds 200 on `/service/rest/v1/status`.
- [ ] `package-cache` and `registry-cache` can be active concurrently
      under the same `cache` profile without port or volume conflict.
- [ ] The `Profile` class in
      `cli/deploy/development/profile.py` activates the `cache` profile
      for local dev (status quo) and inactivates it for CI; the same
      gate applies to both `registry-cache` and `package-cache`.
- [ ] `infinito.depends_on.package-cache` is `required: false` so the
      runner deploys cleanly when the profile is inactive.

### Env defaults

- [ ] `scripts/meta/env/cache/package.sh` exists and exports
      `INFINITO_PACKAGE_CACHE_HOST_PATH`, `INFINITO_PACKAGE_CACHE_HEAP`,
      `INFINITO_PACKAGE_CACHE_DIRECT_MEM`,
      `INFINITO_PACKAGE_CACHE_BLOBSTORE_MAX`, and
      `INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD`.
- [ ] `scripts/meta/env/cache/package.sh` is sourced by
      `scripts/meta/env/all.sh`.
- [ ] `compose.yml` consumes every package-cache env var strictly via
      `${VAR:?…}`. Running `docker compose config` without sourcing the
      env script MUST fail explicitly.

### Bootstrap & repos

- [ ] `scripts/docker/cache/package.sh` exists, is idempotent
      (repeated runs MUST NOT error on already-existing repos), and is
      invoked once on first start under the `cache` profile.
- [ ] On first start, the auto-generated Nexus admin password is
      rotated to the value of
      `INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD`.
- [ ] On first start, the MVP proxy repositories are created:
      `apt-debian`, `apt-ubuntu`, `pypi-proxy`, `npm-proxy`,
      `helm-bitnami`, `raw-githubusercontent`.
- [ ] The blobstore `default` is created with quota
      `INFINITO_PACKAGE_CACHE_BLOBSTORE_MAX`.

### Client wiring

- [ ] Under the `cache` profile, `pip install <pkg>` inside the runner
      pulls through `http://package-cache:8081/repository/pypi-proxy/`.
- [ ] Under the `cache` profile, `npm install <pkg>` inside the runner
      pulls through `http://package-cache:8081/repository/npm-proxy/`.
- [ ] Under the `cache` profile, `apt-get update && apt-get install`
      inside the runner pulls through
      `http://package-cache:8081/repository/apt-…/`.
- [ ] Under the `cache` profile, `helm pull` against the bitnami chart
      proxy URL succeeds against the cache.
- [ ] When the `cache` profile is INACTIVE, all client-config binds
      fall back to `/dev/null` and package managers default to
      upstream — no failed deploys.

### Coexistence with `registry-cache`

- [ ] This requirement does NOT modify the existing `registry-cache`
      service or its CA / proxy.conf wiring.
- [ ] Docker image pulls continue to flow through `registry-cache`;
      `package-cache` is NOT registered as a Docker registry mirror in
      the runner's dockerd.

### Tests

- [ ] An integration test (e.g. under `tests/integration/`) brings up
      the `cache` profile, executes a representative `pip install` and
      `apt-get install` inside the runner, and verifies via the Nexus
      access log (or by pointing one upstream at an unreachable host
      and confirming the install still succeeds via the cache) that
      packages were served by `package-cache`.
- [ ] `make test` passes.

### Documentation

- [ ] `compose/package-cache/README.md` exists and mirrors the
      structure of
      [compose/registry-cache/README.md](../../compose/registry-cache/README.md):
      Activation, Scope, Files, env-var contract pointer.
- [ ] `docs/contributing/artefact/files/compose.yml.md` documents the
      package-cache env-var contract beside the existing Registry
      Cache section.

## Validation Apps

A mix that exercises apt, pip, npm, and helm during deploy:

| App                  | Why it's in the validation set                                  |
|----------------------|-----------------------------------------------------------------|
| `web-app-mediawiki`  | apt + pip during deploy                                         |
| `web-app-discourse`  | npm + ruby gems (gems hit upstream; everything else cached)     |
| any helm-driven role | exercises the `helm-bitnami` proxy                              |

```bash
APPS="web-app-mediawiki web-app-discourse <helm-driven-role>" \
  make deploy-fresh-purged-apps
```

## Prerequisites

Before starting any implementation work, you MUST read
[AGENTS.md](../../AGENTS.md) and follow all instructions in it. The
existing registry-cache wiring (compose service, env script, profile
gate, ExecStartPre helper, bind-mount-with-`/dev/null`-fallback
pattern) is treated as the structural reference; deviating from those
conventions requires explicit justification in the PR description.

## Implementation Strategy

The agent MUST execute this requirement **autonomously**. Open
clarifications only when a decision is genuinely ambiguous and would
otherwise block progress; default to the intent already captured in
this document and proceed.

1. Land the new compose service, env script, and Profile-gate update
   in one branch.
2. Add the bootstrap helper and verify each MVP format manually
   (`pip install requests`, `npm install lodash`, `apt-get install
   jq`, `helm pull bitnami/<chart>`, `curl` against the raw proxy).
3. Add the client-config snippets under `compose/package-cache/`
   and the read-only binds in `compose.yml`.
4. Add the integration test, the README, and the
   `compose.yml.md` section.
5. Run the validation deploy listed above.

## Commit Policy

- The agent MUST NOT create **any** git commit during implementation.
  No partial commits, no checkpoint commits, no per-step commits.
  The working tree evolves in place until both of the following hold:
  - every Acceptance Criterion in this document is checked off
    (`- [x]`);
  - `make test` is green with no skipped suites.
- At that point, the agent lands the whole change set as a single
  commit (or a tight, related sequence) and then instructs the
  operator to run `git-sign-push` outside the sandbox (per
  [CLAUDE.md](../../CLAUDE.md)). The agent MUST NOT push.
