# Local Caches 📦

Three local cache services accelerate re-deploys, reduce upstream traffic, and harden the development workflow against transient upstream outages. They share one compose profile (`cache`) and one override file ([compose/cache.override.yml](../../../compose/cache.override.yml)) and are gated together by [profile.py](../../../cli/administration/deploy/development/profile.py): active on developer machines, inactive on CI runners.

## Services 🧩

### Registry Cache 🐳

[`registry-cache`](../../../compose/registry-cache/README.md) runs `rpardini/docker-registry-proxy` and transparently MITMs every Docker image pull from the inner `dockerd`, regardless of upstream registry (`docker.io`, `ghcr.io`, `mcr.microsoft.com`, …). The runner trusts the proxy CA via [registry-ca.sh](../../../scripts/docker/cache/registry-ca.sh).

Pulls only. Pushes are not intercepted.

### Package Cache 📚

[`package-cache`](../../../compose/package-cache/README.md) runs `sonatype/nexus3` and exposes pull-through proxies for package-manager downloads:

| Format | Repo names | Upstream |
|---|---|---|
| `apt` | `apt-debian`, `apt-debian-security`, `apt-ubuntu`, `apt-ubuntu-security` | `deb.debian.org`, `archive.ubuntu.com`, `security.ubuntu.com` |
| `pypi` | `pypi-proxy` | `pypi.org` (incl. `files.pythonhosted.org`) |
| `npm` | `npm-proxy` | `registry.npmjs.org` |
| `rubygems` | `gem-proxy` | `rubygems.org` |
| `go` | `go-proxy` | `proxy.golang.org` |
| `helm` | `helm-bitnami` | `charts.bitnami.com/bitnami` |
| `yum` | `yum-rocky`, `yum-fedora` | `download.rockylinux.org`, `dl.fedoraproject.org` |
| `raw` | `raw-githubusercontent`, `raw-codeload-github`, `raw-packagist`, `raw-alpine` | `raw.githubusercontent.com`, `codeload.github.com`, `repo.packagist.org`, `dl-cdn.alpinelinux.org` |

Bootstrap is idempotent and runs from [package.sh](../../../scripts/docker/cache/package.sh) once the stack is healthy.

### Package Cache Frontend 🔐

[`package-cache-frontend`](../../../compose/package-cache-frontend/README.md) runs `nginx:alpine` and reverse-proxies upstream package-manager hostnames onto the matching Nexus repo path. Combined with `extra_hosts` DNS-hijack on consumers, package managers can hit their real upstream URL and still flow through the cache.

Two listener layers:

- HTTPS (port 443): per-hostname server certs signed by a dedicated CA. Used by the `infinito` runner (Ansible-driven `pip install`, `gem install`, `composer install`, `curl https://…`). The runner trusts the CA via [package-frontend-ca.sh](../../../scripts/docker/cache/package-frontend-ca.sh).
- HTTP (port 80): plain mirrors for `deb.debian.org`, `archive.ubuntu.com`, `security.ubuntu.com`, `dl-cdn.alpinelinux.org`. Used by inner-`dockerd` Dockerfile builds via `build.extra_hosts` DNS-hijack. No CA-trust required in the build container.

Cert generation runs in a throw-away alpine container driven by [package-frontend-certs.sh](../../../scripts/docker/cache/package-frontend-certs.sh) before the frontend starts.

## Activation 🎚️

The `cache` decision is exposed via `Profile.registry_cache_active()` in [profile.py](../../../cli/administration/deploy/development/profile.py). When active:

- [compose/cache.override.yml](../../../compose/cache.override.yml) is layered on top of the base [compose.yml](../../../compose.yml) by [compose.py](../../../cli/administration/deploy/development/compose.py) and [down.py](../../../cli/administration/deploy/development/down.py) via [common.py](../../../cli/administration/deploy/development/common.py)`compose_file_args`.
- The cache services are added.
- The runner's `infinito` service receives:
  - bind-mounts for the registry-cache CA, the package-cache client snippets (`pip.conf`, `npmrc`, `apt.list`), and the frontend CA file
  - `extra_hosts` entries DNS-hijacking the HTTPS upstream hostnames to the frontend's static IP
  - `INFINITO_CACHE_PACKAGE_FRONTEND_IP` env var for the inner compose wrapper
- Cert generation, Nexus repo bootstrap, and runner trust-store install run from [compose.py](../../../cli/administration/deploy/development/compose.py).

When inactive, the override is omitted: cache services do not exist, the runner has no cache mounts or DNS-hijack, package managers go direct to upstream.

CI signals (`GITHUB_ACTIONS=true`, `INFINITO_RUNNING_ON_GITHUB=true`, `CI=true`) deactivate. Fresh runner disks per CI job give no cross-run amortization.

## Coverage Matrix 📋

| Traffic | Mechanism | Cached |
|---|---|---|
| Image pulls (any registry, inner `dockerd`) | `registry-cache` MITM via `HTTP_PROXY` env on `dockerd` | ✓ |
| `apt-get install` (Ansible task in runner) | `apt.list` URL-rewrite to `package-cache:8081` | ✓ |
| `pip install` (Ansible task in runner) | `pip.conf` URL-rewrite | ✓ |
| `npm install` (Ansible task in runner) | `.npmrc` URL-rewrite | ✓ |
| `gem`, `composer`, `go`, `curl https://…` (Ansible task in runner) | DNS-hijack + frontend HTTPS + runner CA-trust | ✓ |
| `RUN apt-get install` (inner Dockerfile build, Debian/Ubuntu) | `build.extra_hosts` DNS-hijack + frontend HTTP | ✓ |
| `RUN apk add` (inner Dockerfile build, Alpine ≤3.17 HTTP) | `build.extra_hosts` DNS-hijack + frontend HTTP | ✓ |
| `RUN pip/npm/gem/composer/go install` (inner Dockerfile build) | none today | ✗ |
| `RUN apk add` (Alpine ≥3.18 HTTPS) | none today | ✗ |
| App container runtime traffic (HTTPS to external API) | none today | ✗ |

The HTTPS-only inner-build gap requires per-image CA-trust bootstrap, which is out of scope for the current minimal-invasive design.

## Compose Wrapper Auto-Detection 🪄

The runner's `compose` wrapper at [roles/sys-svc-compose/files/compose.py](../../../roles/sys-svc-compose/files/compose.py) auto-detects compose files when invoked from per-app directories under `/opt/compose/<app>/`:

| File | When |
|---|---|
| `compose.yml` | always |
| `compose.override.yml` | when present (role provides it) |
| `compose.ca.override.yml` | when present (TLS self-signed CA-inject runs) |
| `compose.cache.override.yml` | generated on the fly when `INFINITO_CACHE_PACKAGE_FRONTEND_IP` is set; emits `build.extra_hosts` for every service that has a `build:` key |

[pull.py](../../../roles/sys-svc-compose/files/pull.py) delegates to the same wrapper so `pull` and `build --pull` operations see the identical `-f` set.

## Environment Variables 🌳

The host-side env-vars (`INFINITO_CACHE_REGISTRY_*`, `INFINITO_CACHE_PACKAGE_*`) are declared in [default.env](../../../default.env) and the dynamic ones (cache sizes from `df`/`/proc/meminfo`, sha256 admin password) are computed by [utils/env/builder.py](../../../utils/env/builder.py). `make dotenv` writes them into `.env`, which Compose auto-loads and which `BASH_ENV` makes available to every Makefile recipe through [scripts/meta/env/load.sh](../../../scripts/meta/env/load.sh). See [variables.md](variables.md).

Per-variable defaults and purposes are in [compose.yml.md](../artefact/files/compose.yml.md) under the cache section.

`INFINITO_CACHE_PACKAGE_MAX_AGE_MIN` (default `8640` = 6 days) controls how long every Nexus proxy repo holds an upstream response before revalidating. The bootstrap helper applies it as `contentMaxAge`, `metadataMaxAge`, and `negativeCache.timeToLive`. The default is intentionally one day below the 7-day `Valid-Until` window Debian and Ubuntu generate in their apt `Release` files, so Nexus always refreshes the manifest before `apt-get update` would see it expired. Raise it for slow-moving upstreams when staleness is preferable to upstream load; lower it further for fast-moving feeds (`apt-debian-security`, branch-pinned tarballs) when staleness becomes visible.

## Operations 🛠️

| Action | Command |
|---|---|
| Start the stack with caches | `make compose-up` |
| Stop the stack | `make compose-down` |
| Wipe local cache state | `make clean-cache` |
| Manually re-bootstrap Nexus repos | `bash scripts/docker/cache/package.sh` (after `make dotenv` or sourcing `scripts/meta/env/load.sh`) |
| Manually regenerate frontend certs | `bash scripts/docker/cache/package-frontend-certs.sh` |
| Reload nginx in the frontend | `docker exec infinito-package-cache-frontend nginx -s reload` |
| Inspect cache hits | `docker logs -f infinito-package-cache` and `docker logs -f infinito-package-cache-frontend` |

Cache state persists under `/var/cache/infinito/core/cache/`. Paths are configurable via the env scripts above.

## Adding a New Upstream ➕

When a new package manager or upstream needs caching:

1. Register a Nexus proxy repo in [package.sh](../../../scripts/docker/cache/package.sh).
2. If the upstream uses HTTPS, add it to `HOSTNAMES` in [package-frontend-certs.sh](../../../scripts/docker/cache/package-frontend-certs.sh) so a leaf cert is issued.
3. Add a server-block in [upstreams.conf](../../../compose/package-cache-frontend/upstreams.conf) that reverse-proxies onto the new Nexus repo path (rewrite if upstream URL prefix differs from the Nexus repo path).
4. Add an `extra_hosts` entry on the `infinito` service in [compose/cache.override.yml](../../../compose/cache.override.yml) for runner-side traffic.
5. If the upstream is HTTP-only and inner-`dockerd` builds need it, also add it to `_CACHE_HTTP_HOSTNAMES` in [compose.py](../../../roles/sys-svc-compose/files/compose.py) so the per-app `compose.cache.override.yml` includes it in `build.extra_hosts`.

## Background 📚

- Compose-file env-var contract: [compose.yml.md](../artefact/files/compose.yml.md)
- Profile gating mechanics: [profile.py](../../../cli/administration/deploy/development/profile.py)
