# `compose.yml` 🐳

This page documents the rules that govern the top-level [compose.yml](../../../../compose.yml) and the environment variables it consumes.
For general documentation rules (links, writing, RFC 2119 keywords), see [documentation.md](../../documentation.md).
For CI debugging workflows that use these variables, see [ci.md](../../actions/debugging/ci.md).

## Purpose 🎯

The top-level `compose.yml` is scoped to **local development and CI testing only**.
It MUST NOT be used to deploy or run a live Infinito.Nexus stack.
Production deployments MUST go through the Ansible roles and their own rendered compose files under `roles/<role>/templates/`.

Within its scope, `compose.yml` MUST stay a thin orchestration surface for the `infinito` runner container and its CoreDNS sidecar.
It MUST NOT host application roles, fixtures, or test harnesses.

## Structure 📐

- You MUST keep every service in `compose.yml` behind a `profiles:` entry so that `docker compose up` without a profile stays a no-op.
- You MUST expose tunable runtime parameters as env vars with safe defaults inline in the compose key (e.g. `${VAR:-default}`).
- You MUST NOT hardcode values that differ between operators (paths, image tags, CPU or memory caps).
- You SHOULD annotate non-obvious keys with a short inline comment that explains why they exist, not what they do.
- You MUST document every new env var in the table below when you add it to `compose.yml`.

## Environment Variables 📋

All variables consumed by [compose.yml](../../../../compose.yml). Variables without a default are REQUIRED when the `ci` profile is active.

### Image and Runtime

| Variable                 | Default         | Purpose                                                                 |
|--------------------------|-----------------|-------------------------------------------------------------------------|
| `INFINITO_IMAGE`         | none (required) | Image reference used by the `infinito` service.                         |
| `INFINITO_PULL_POLICY`   | `never`         | Compose `pull_policy`. Keep `never` for local builds, `always` for CI.  |
| `INFINITO_CONTAINER`     | none (required) | Used directly as `container_name`. Derived from `INFINITO_DISTRO` by [defaults.sh](../../../../scripts/meta/env/defaults.sh); compose.yml reads it strictly via `${INFINITO_CONTAINER:?...}`. |
| `INFINITO_COMPILE`       | `1`             | Passed into the container; toggles in-container compilation steps.      |
| `NIX_CONFIG`             | none            | Build-arg forwarded to the Dockerfile for Nix configuration.            |

### Resource Caps (OOM Reproduction)

These variables cap the `infinito` container so local runs can reproduce GitHub-hosted runner pressure.
Each default is `0`, which Docker interprets as "unlimited" and is identical to omitting the key.
See [ci.md](../../actions/debugging/ci.md) for runner specs and reproduction profiles.

| Variable                 | Compose key      | Default | Example |
|--------------------------|------------------|---------|---------|
| `INFINITO_MEM_LIMIT`     | `mem_limit`      | `0`     | `16g`   |
| `INFINITO_MEMSWAP_LIMIT` | `memswap_limit`  | `0`     | `16g`   |
| `INFINITO_CPUS`          | `cpus`           | `0`     | `4`     |

You SHOULD set `INFINITO_MEMSWAP_LIMIT` to the same value as `INFINITO_MEM_LIMIT` to disable swap inflation.
Allowing swap masks OOM conditions that the real runner would hit.

### Storage

| Variable                  | Default            | Purpose                                                          |
|---------------------------|--------------------|------------------------------------------------------------------|
| `INFINITO_DOCKER_VOLUME`  | `docker`           | Named volume (or host path) backing the nested Docker directory. |
| `INFINITO_DOCKER_MOUNT`   | `/var/lib/docker`  | Mount point inside the container for the nested Docker data.     |

### Registry Cache

The `registry-cache` service runs `rpardini/docker-registry-proxy` as a
pull-through MITM proxy in front of every outbound docker registry pull
made by `infinito`'s inner dockerd. Catch-all caching: first request to
any registry (`docker.io`, `ghcr.io`, `quay.io`, `registry.k8s.io`, …)
is fetched and persisted; re-requests are served from cache.

The service sits in its own `cache` profile, separate from the always-on
`ci` profile that carries `coredns` and `infinito`. Profile activation
is decided by [Profile](../../../../cli/deploy/development/profile.py):

- **Local dev**: `cache` profile active, `registry-cache` runs, `infinito`
  routes pulls through the proxy. Cross-run image dedup pays off here
  because the host disk persists between deploys.
- **CI runs** (`GITHUB_ACTIONS=true`, `RUNNING_ON_GITHUB=true`, or
  `CI=true`): `cache` profile inactive, `registry-cache` does not start,
  `infinito.depends_on.registry-cache` is `required: false` so Compose
  does not pull it in via the dependency. Fresh runner disks would not
  benefit from cross-run dedup; the proxy startup overhead is net loss.

Wiring inside `infinito` (all bind-mounted directly via `compose.yml`,
no Dockerfile or entry.sh staging, so edits take effect on the next
container start without an image rebuild):

- the registry-cache CA bundle at `/opt/registry-cache-ca` (read-only),
- the systemd drop-in source path is gated by
  `INFINITO_REGISTRY_CACHE_PROXY_CONF`. The dev tooling sets it to
  [proxy.conf](../../../../compose/registry-cache/proxy.conf) when the
  `cache` profile is active and leaves it at `/dev/null` otherwise, so
  systemd reads an empty drop-in when the proxy is not running and
  dockerd boots without `HTTP_PROXY`,
- the install script
  [registry-ca.sh](../../../../scripts/docker/cache/registry-ca.sh)
  at `/usr/local/bin/registry-cache-ca.sh` (must keep its git
  +x bit; bind-mounts preserve host permissions).

When the proxy is active, the drop-in registers the install script as
`ExecStartPre`. dockerd is gated on `registry-cache` health
(`condition: service_healthy`) so the CA is on disk before
`ExecStartPre` runs. Pulls only. Pushes are not intercepted.

| Variable                                | Default                                | Purpose                                                                                                              |
|-----------------------------------------|----------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| `INFINITO_REGISTRY_CACHE_HOST_PATH`     | none (required)                        | Host path bind-mounted into `registry-cache` for blob/manifest persistence. Default supplied by [registry.sh](../../../../scripts/meta/env/cache/registry.sh) (`/var/cache/infinito/core/cache/registry/mirror`). |
| `INFINITO_REGISTRY_CACHE_CA_HOST_PATH`  | none (required)                        | Host path holding the proxy MITM CA bundle. Mounted writable into `registry-cache`, read-only into `infinito`. Default supplied by [registry.sh](../../../../scripts/meta/env/cache/registry.sh) (`/var/cache/infinito/core/cache/registry/ca`). |
| `INFINITO_REGISTRY_CACHE_MAX_SIZE`      | none (required)                        | Maximum on-disk size of the cache. Older entries are evicted when reached. Default computed by [registry.sh](../../../../scripts/meta/env/cache/registry.sh) as half the free disk space at the cache path, minimum `1g`, fallback `2g` if `df` fails. |
| `INFINITO_REGISTRY_CACHE_PROXY_CONF`    | `/dev/null`                            | Bind-mount source for the systemd drop-in inside `infinito`. Set by the dev tooling to the real `proxy.conf` only when the `cache` profile is active; the `/dev/null` default makes systemd load an empty drop-in so dockerd boots without `HTTP_PROXY`. |

### Package Cache

The `package-cache` service runs `sonatype/nexus3` as a Sonatype Nexus
3 OSS instance and exposes pull-through proxy repositories for
package-manager downloads from the runner: pypi, npm, apt
(Debian and Ubuntu), helm, raw. Companion to the registry-cache,
which covers Docker image pulls. Both services share the `cache`
compose profile and the same `Profile` gate (active locally,
inactive in CI).

`infinito.depends_on.package-cache` is `condition: service_healthy,
required: false`: with the `cache` profile inactive, Compose neither
starts the proxy nor blocks the runner. With the profile active, the
runner waits for Nexus's REST API to answer before starting.

Three client-config snippets in
[compose/package-cache/](../../../../compose/package-cache/) bind-mount
into the runner via `${INFINITO_PACKAGE_CACHE_*_CONF:-/dev/null}` env
vars (set by the [Profile](../../../../cli/deploy/development/profile.py)
class only when `cache` is active): `pip.conf` -> `/etc/pip.conf`,
`npmrc` -> `/root/.npmrc`, `apt.list` ->
`/etc/apt/sources.list.d/package-cache.list`. With the profile off,
the bind sources fall back to `/dev/null` and package managers default
to upstream traffic.

A host-side bootstrap helper
[package.sh](../../../../scripts/docker/cache/package.sh)
runs once after the stack is healthy, invoked from
[up.py](../../../../cli/deploy/development/compose.py). It rotates the
auto-generated admin password, creates a single blobstore quota'd to
`INFINITO_PACKAGE_CACHE_BLOBSTORE_MAX`, and registers the MVP set of
proxy repos: `apt-debian`, `apt-ubuntu`, `pypi-proxy`, `npm-proxy`,
`helm-bitnami`, `raw-githubusercontent`. The helper is idempotent.

| Variable                                | Default          | Purpose                                                                                                              |
|-----------------------------------------|------------------|----------------------------------------------------------------------------------------------------------------------|
| `INFINITO_PACKAGE_CACHE_HOST_PATH`      | none (required)  | Host path bind-mounted at `/nexus-data` inside the proxy. Default supplied by [package.sh](../../../../scripts/meta/env/cache/package.sh) (`/var/cache/infinito/core/cache/package/data`). |
| `INFINITO_PACKAGE_CACHE_HEAP`           | none (required)  | JVM heap (`-Xms` / `-Xmx`). Default computed by [package.sh](../../../../scripts/meta/env/cache/package.sh) as half free RAM, capped at `2g`, floor `1g` (Nexus 3 OSS minimum). |
| `INFINITO_PACKAGE_CACHE_DIRECT_MEM`     | none (required)  | `MaxDirectMemorySize`. Default mirrors `INFINITO_PACKAGE_CACHE_HEAP`.                                                |
| `INFINITO_PACKAGE_CACHE_BLOBSTORE_MAX`  | none (required)  | Soft quota for the default blobstore, applied during bootstrap. Default computed as half the free disk space at the cache path, floor `2g`. |
| `INFINITO_PACKAGE_CACHE_ADMIN_PASSWORD` | none (required)  | Target value for the rotated Nexus admin password. Operator-supplied; the env script synthesises a stable per-host hash if unset. |
| `INFINITO_PACKAGE_CACHE_PORT`           | `8081`           | Host-side port that maps to Nexus's `8081` (UI / REST). Bound to `${BIND_IP}` only.                                  |
| `INFINITO_PACKAGE_CACHE_PIP_CONF`       | `/dev/null`      | Bind source for `/etc/pip.conf`. Set by the dev tooling to `compose/package-cache/pip.conf` when the `cache` profile is active. |
| `INFINITO_PACKAGE_CACHE_NPMRC`          | `/dev/null`      | Bind source for `/root/.npmrc`. Set to `compose/package-cache/npmrc` when active.                                    |
| `INFINITO_PACKAGE_CACHE_APT_LIST`       | `/dev/null`      | Bind source for `/etc/apt/sources.list.d/package-cache.list`. Set to `compose/package-cache/apt.list` when active.   |

### Networking

| Variable                      | Default          | Purpose                                                                |
|-------------------------------|------------------|------------------------------------------------------------------------|
| `DNS_IP`                      | none (required)  | Static IP assigned to the CoreDNS sidecar and used as the DNS server.  |
| `IP4`                         | none (required)  | Static IPv4 address assigned to the `infinito` container.              |
| `DOMAIN`                      | none (required)  | Base domain exported into the container environment.                   |
| `BIND_IP`                     | `127.0.0.1`      | Host address that all published ports bind to.                         |
| `SUBNET`                      | `172.30.0.0/24`  | IPAM subnet for the default bridge network.                            |
| `GATEWAY`                     | `172.30.0.1`     | IPAM gateway for the default bridge network.                           |
| `INFINITO_OUTER_NETWORK_MTU`  | `1500`           | MTU for the bridge network. Lower when the host network is tunneled.   |

## Adding a Variable ➕

When you introduce a new env var in `compose.yml`, you MUST:

1. Use the `${VAR:-default}` form if a sensible default exists. If no default is safe, use `${VAR}` and treat the variable as REQUIRED.
2. Add a row to the matching table above with default and purpose.
3. Cross-link the variable from the relevant workflow page when the variable only exists to drive a specific workflow (e.g. resource caps link to [ci.md](../../actions/debugging/ci.md)).
