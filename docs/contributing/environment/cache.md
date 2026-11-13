# Local Caches 📦

Three local cache services and one shared cache folder accelerate re-deploys, reduce upstream traffic, and harden the development workflow against transient upstream outages. They share one override file ([compose/cache.override.yml](../../../compose/cache.override.yml)) and are gated together by [profile.py](../../../cli/administration/deploy/development/profile.py): active on developer machines, inactive on CI runners. Every cache has a fixed size cap and an idle window, see [Bounds and Eviction](#bounds-and-eviction-).

## Services 🧩

### Registry Cache 🐳

[`registry-cache`](../../../compose/registry-cache/README.md) runs `rpardini/docker-registry-proxy` and transparently MITMs every Docker image pull from the inner `dockerd`, regardless of upstream registry (`docker.io`, `ghcr.io`, `mcr.microsoft.com`, …). The runner trusts the proxy CA via [registry-ca.sh](../../../scripts/docker/cache/registry-ca.sh).

Pulls only. Pushes are not intercepted.

### Package Cache 📚

[`package-cache`](../../../compose/package-cache/README.md) runs `sonatype/nexus3` and exposes pull-through proxies for package-manager downloads:

| Format | Repo names | Upstream |
|---|---|---|
| `apt` | `apt-debian`, `apt-debian-security`, `apt-ubuntu`, `apt-ubuntu-security` | `deb.debian.org`; both Ubuntu repos take the first entry of `INFINITO_APT_UBUNTU_MIRRORS` |
| `apt` (mirrors) | `apt-debian-mirror`, `apt-debian-security-mirror`, `apt-ubuntu-mirror`, `apt-ubuntu-security-mirror` | `ftp.debian.org`, `security.debian.org`; both Ubuntu repos take the second entry of `INFINITO_APT_UBUNTU_MIRRORS` |
| `pypi` | `pypi-proxy` | `pypi.org` (incl. `files.pythonhosted.org`) |
| `npm` | `npm-proxy` | `registry.npmjs.org` |
| `rubygems` | `gem-proxy` | `rubygems.org` |
| `go` | `go-proxy` | `proxy.golang.org` |
| `helm` | `helm-bitnami` | `charts.bitnami.com/bitnami` |
| `yum` | `yum-rocky`, `yum-fedora` | `download.rockylinux.org`, `download.fedoraproject.org` |
| `raw` | `raw-githubusercontent`, `raw-codeload-github`, `raw-packagist`, `raw-alpine` | `raw.githubusercontent.com`, `codeload.github.com`, `repo.packagist.org`, `dl-cdn.alpinelinux.org` |
| `raw` (no hijacked host) | `raw-nixos-cache` | `cache.nixos.org` |

A proxy repo that holds a cached copy serves it when its remote is unreachable, regardless of `metadataMaxAge` (measured). `autoBlock` is therefore off: while a remote is auto-blocked Nexus answers `404 Remote Auto Blocked` instead of falling back to that cached copy. The mirror repos below only come into play when nothing is cached either.

Every apt suite exists twice, once per upstream mirror. Nexus has no group repository type for `apt` (only maven, raw, docker, yum, npm, pypi, rubygems, go and friends), so the failover lives in the frontend: a request that the primary repo answers with `502`/`503`/`504` is re-run against the `-mirror` repo, which proxies a different host. `404` deliberately does not retry, because a missing file is missing on both mirrors and apt probes for missing files often. The frontend waits at most 8 s for a primary before it re-runs the request against the mirror; the `-mirror` locations keep the global 300 s.

Bootstrap is idempotent and runs from [bootstrap.sh](../../../roles/svc-cache-package/files/shell/bootstrap.sh) once the stack is healthy. It loops over `INFINITO_CACHE_UPSTREAMS` and holds no repository of its own.

### Package Cache Frontend 🔐

[`package-cache-frontend`](../../../compose/package-cache-frontend/README.md) runs `nginx:alpine` and reverse-proxies upstream package-manager hostnames onto the matching Nexus repo path. Combined with `extra_hosts` DNS-hijack on consumers, package managers can hit their real upstream URL and still flow through the cache.

Two listener layers:

- HTTPS (port 443): per-hostname server certs signed by a dedicated CA. Used by the `infinito` runner (Ansible-driven `pip install`, `gem install`, `composer install`, `curl https://…`). The runner trusts the CA via [ca.sh](../../../roles/svc-cache-package/files/shell/ca.sh).
- HTTP (port 80): plain mirrors for `deb.debian.org`, `archive.ubuntu.com`, `security.ubuntu.com`, `dl-cdn.alpinelinux.org`. Used by inner-`dockerd` Dockerfile builds via `build.extra_hosts` DNS-hijack. No CA-trust required in the build container.

Cert generation runs in a throw-away alpine container driven by [certs.sh](../../../roles/svc-cache-package/files/shell/certs.sh) before the frontend starts. It issues a leaf for each name in `INFINITO_CACHE_TLS_HOSTS` and holds no hostname of its own.

### Shared Package Cache Folder 🗂️

One host folder, `INFINITO_CACHE_SHARED_HOST_PATH` (default `<DIR_CACHE>/shared`, written by [paths.py](../../../utils/env/handlers/infinito/cache/paths.py)), holds the package and tool caches of every compose slot, swarm lab node and GUI lane on the host. Every consumer mounts it read-write at the same path it has on the host. Both cache variables are optional: an empty or missing value layers no mount, no cache environment and no pacman layering, so a checkout whose `.env` predates them renders and starts as before.

| Subfolder | Tool | How the consumer points at it |
|---|---|---|
| `pacman/` | pacman | last `CacheDir` in `/etc/pacman.conf`, written by [pacman.sh](../../../scripts/docker/cache/pacman.sh); each node downloads into its own `pacman/node-XXXXXX/` |
| `pip/` | pip | `PIP_CACHE_DIR` |
| `npm/` | npm | `npm_config_cache` |
| `ms-playwright/` | Playwright browsers | `PLAYWRIGHT_BROWSERS_PATH` |

The consumers in this repository are wired as follows:

- Compose slots: `compose_file_args` layers [compose/shared-cache.override.yml](../../../compose/shared-cache.override.yml) when the cache stack is active and the variable is set. It mounts the folder and `pacman.sh` into the runner and sets `PIP_CACHE_DIR` and `npm_config_cache`. `make compose-up` then runs `pacman.sh` in the runner.
- Swarm lab nodes: `01_bootstrap.sh` layers [compose/swarm/shared-cache.override.yml](../../../compose/swarm/shared-cache.override.yml) next to the cache override when the variable is set. It mounts the folder and `pacman.sh` into the manager, both workers, the NFS server and the backup host, and [playbook.yml](../../../compose/swarm/playbook.yml) runs `pacman.sh` on each node that has it.
- Act job containers: [workflow.sh](../../../scripts/tests/deploy/act/workflow.sh) wires the folder under the condition `01_bootstrap.sh` uses for the swarm lab nodes, a set variable and an existing `infinito-package-cache-frontend` container. It mounts the folder into every job container it starts, sets `PIP_CACHE_DIR` and blanks `cache: pip` in the copy of the workflow it hands to act, so `actions/setup-python` neither archives the folder after a job nor extracts an old archive into it, and the `make install-force` of each job reuses the wheels the host already downloaded. The deploy workflows on GitHub runners never call the wrapper. The workspace suite ([call-test-workspace.yml](../../../.github/workflows/call-test-workspace.yml)) does, through `make swarm-zombie`, and there too the act jobs get the folder exactly when the lab nodes of the same run get it: whenever the suite's own cache stack is up at that point.
- Core Playwright runs take their browsers from the `mcr.microsoft.com/playwright` image, so they leave `ms-playwright/` empty.

pacman on an arch stack reads up to three cache directories. `INFINITO_CACHE_HOST_PACMAN_PATH`, written by [host_pacman_path.py](../../../utils/env/handlers/infinito/cache/host_pacman_path.py), is the first `CacheDir` of the host's `pacman-conf`, and only on a host whose `/etc/os-release` `ID` is exactly `arch` running an arch stack. On Manjaro, EndeavourOS and every other host, and on every stack that does not run pacman, the variable is empty and pacman uses the shared layer alone. When it is set, [compose/pacman.override.yml](../../../compose/pacman.override.yml) and [compose/swarm/pacman.override.yml](../../../compose/swarm/pacman.override.yml) mount it read-only at the same path, layered only together with the shared folder. `pacman.sh` lists it as the first `CacheDir`, the node's own download directory `<shared>/pacman/node-XXXXXX/` as the second and `<shared>/pacman/` as the third. `pacman.sh` creates the node download directory with `mktemp` on its first run and reuses the one already listed in `pacman.conf` on every later run. pacman finds a package in any of the three directories and downloads a missing one, `.part` file included, into the node download directory, the first one it can write. The `PostTransaction` hook `pacman.sh` writes to `pacman.d/hooks/infinito-shared-cache.hook` beside `pacman.conf` then renames every finished package and signature from the node download directory into `<shared>/pacman/` and leaves `.part` files there for the next resume. `pacman.sh` fails when `pacman.conf` sets `HookDir`. The disc-space cleanup runs `pacman -Sc` per writable `CacheDir`, so it never touches the read-only layer.

apt and dnf keep their per-container caches. Their downloads come through the `apt-*` and `yum-*` proxies of the package cache, which store each file once for the whole host.

A GUI lane follows the same contract whenever `INFINITO_CACHE_SHARED_HOST_PATH` is non-empty, and mounts nothing when it is empty:

- Mount `${INFINITO_CACHE_SHARED_HOST_PATH}` read-write at `${INFINITO_CACHE_SHARED_HOST_PATH}`.
- Set `PIP_CACHE_DIR=${INFINITO_CACHE_SHARED_HOST_PATH}/pip`, `npm_config_cache=${INFINITO_CACHE_SHARED_HOST_PATH}/npm` and `PLAYWRIGHT_BROWSERS_PATH=${INFINITO_CACHE_SHARED_HOST_PATH}/ms-playwright`.
- On an arch lane with a non-empty `INFINITO_CACHE_HOST_PACMAN_PATH`, mount that directory read-only at the same path and run `scripts/docker/cache/pacman.sh /etc/pacman.conf "${INFINITO_CACHE_SHARED_HOST_PATH}" "${INFINITO_CACHE_HOST_PACMAN_PATH}"` in the lane before its first `pacman` call. Pass an empty third argument without the read-only mount.
- Read both values from this checkout's `.env` after `make dotenv`.

### Host Cache Sync 🔁

`INFINITO_CACHE_HOST_SYNC` (default `false`, from [default.env](../../../default.env)) decides what `make cache-host-sync` does to the host itself. Nothing else reads it, so every rendered compose file and cache configuration stays the same either way, and the host stays untouched until the operator runs the target. The target runs [host_sync.py](../../../utils/cache/host_sync.py) under `sudo` and passes this checkout's `.env` values as arguments.

With `true`:

- On a host whose `/etc/os-release` `ID` is exactly `arch`, `/etc/pacman.conf` gains `CacheDir = <INFINITO_CACHE_SHARED_HOST_PATH>/pacman/` after its last `CacheDir`, with the default `/var/cache/pacman/pkg/` listed first where it lists none. The host keeps downloading into its own cache, which an arch stack mounts read-only through `INFINITO_CACHE_HOST_PACMAN_PATH`, and installs every package the stack published to the shared folder without a download. Every `SigLevel` stays: the host's pacman checks each package from the shared folder against its own sync database, since every stack container can write there. `pacman -Sc` on the host asks per `CacheDir`; a yes for the shared folder evicts the stack's packages.
- On a Debian or Ubuntu host, every `deb` entry of `/etc/apt/sources.list`, `/etc/apt/sources.list.d/*.list` and `/etc/apt/sources.list.d/*.sources` whose archive and suite an `apt-*` repository of the package cache serves gets a copy pointing at `http://<INFINITO_BIND_IP>:<INFINITO_CACHE_PACKAGE_PORT>/repository/<repo>/`, inserted before it with every option, `Signed-By` included. The original stays behind the copy, so apt falls back to it while the stack is down. Other suites, third-party repositories, disabled stanzas, entries that set `trusted`, `allow-insecure`, `allow-weak` or `allow-downgrade-to-insecure` to anything but `no`, `false`, `without`, `off`, `disable` or `0`, and HTTPS entries the cache would fetch over HTTP stay as they are. `/etc/apt/apt.conf.d/99infinito-cache-host-sync` sets `APT::Keep-Downloaded-Packages "false"`, so Nexus holds the one copy of each package.
- Before anything is written, `pacman-conf` reads the planned `pacman.conf`, or `apt-get update` fetches the planned entries alone, with `APT::Update::Error-Mode=any` so a transient network error fails it too. When it refuses, every file stays as it was.
- The original and the digest of every changed file go to `<DIR_VAR_LIB>/cache-host-sync/`. A rerun restores them first and plans again.

With `false`, the target restores every recorded file byte for byte and removes the drop-in. It restores nothing while a recorded file changed since the sync, and names that file and the original it keeps. Any other host `ID` with `true` is refused.

## Bounds and Eviction 📏

Every cache has a fixed cap and the idle window `INFINITO_CACHE_MAX_IDLE_DAYS` (default `30`): an entry without access for that many days is evicted. `make dotenv` writes the defaults below from [default.env](../../../default.env); an exported value or a line in [custom.env](../customize.md) wins, and no value depends on the free disk space.

| Cache | Path | Cap variable | Default | Age eviction | Size eviction |
|---|---|---|---|---|---|
| Registry mirror | `INFINITO_CACHE_REGISTRY_HOST_PATH` | `INFINITO_CACHE_REGISTRY_MAX_SIZE` | `40g` | nginx `proxy_cache_path inactive=<idle window>d`, set by [entrypoint.sh](../../../compose/registry-cache/entrypoint.sh) | the nginx cache manager evicts the least recently used blobs above `max_size` |
| Nexus | `INFINITO_CACHE_PACKAGE_HOST_PATH` | `INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX` | `20g` | the cleanup policy `infinito-idle` (last downloaded before the idle window) on every proxy repository, run daily at 01:00 by the `Cleanup service` task Nexus creates itself, followed by the daily compaction of the `default` blob store at 02:00 UTC that the bootstrap schedules | `make cache-evict` runs the cleanup, the unused asset blob cleanup and the compaction, then deletes the least recently downloaded assets and repeats the last two until the blob store is at or below the cap |
| Shared folders | `INFINITO_CACHE_SHARED_HOST_PATH` (pip, npm, pacman, ms-playwright together) | `INFINITO_CACHE_SHARED_MAX_SIZE` | `10g` | `make cache-evict` removes files without access in the idle window | then the least recently accessed files, until all shared folders together are at or below the one cap |
| Models | `INFINITO_TOOLS_MODELS_HOST_PATH` | `INFINITO_TOOLS_MODELS_MAX_SIZE` | `30g` | `make cache-evict` removes model units without use in the idle window | then the least recently used units, until the folder is at or below the cap |
| Host build cache | the host Docker daemon's BuildKit store | `INFINITO_BUILD_CACHE_MAX_SIZE` | `20g` | none | every image build of [build.sh](../../../scripts/image/build.sh) ends with [prune.sh](../../../scripts/image/prune.sh), a `docker builder prune` that keeps at most the cap |

The sweeper of the shared folders and the models removes related files together: an npm `_cacache` index bucket with the content files only it references, a pip `http-v2` entry with its `.body`, a pacman package with its `.sig`, and a Playwright browser directory as a whole; `ms-playwright/.links` stays. A model unit is a whole package directory or file below a tool's folder (`models/libretranslate/<package>`), or an Ollama manifest together with the blobs no other manifest references; the sweeper skips the models folder while a running container mounts it. A store entry `models/<sha256>` of a [pinned artefact](#pinned-artefacts-) that the calling checkout or the pinned commit declares is never evicted, whatever its age and the cap; while the pinned commit's declarations cannot be read, the sweeper skips the models folder and says so. It never removes a cache root, a directory that is not a unit, or anything outside the cache paths. On a filesystem mounted `noatime` it reads the modification time instead of the access time, and `make cache-status` reports `atime_fallback: true` for that cache.

The prune flag that keeps a storage amount changed its name between Docker releases: [prune.sh](../../../scripts/image/prune.sh) uses `--max-used-space` when `docker builder prune --help` lists it, else `--keep-storage`, and fails the build when the engine offers neither.

`make cache-evict` first checks the disk floor `INFINITO_CACHE_DISK_FLOOR` (default `15g`): the caps fit the machine only when `free + used - sum(caps)` reaches it. Otherwise it exits non-zero before it evicts anything and names every cap variable. It then sweeps the shared folders and the models and evicts the Nexus blob store through its REST API, and prints one status line per cache. Its first run on a cache above its cap is the migration: the same age and size eviction, so entries accessed inside the idle window stay as far as the cap allows and no cache directory is removed or recreated. `make clean-cache` keeps its wipe semantics and is called by no other target.

The pinned Nexus Community Edition has no public API for cleanup policies or for creating tasks. The [bootstrap](../../../roles/svc-cache-package/files/shell/bootstrap.sh) therefore writes the policy through the internal `/service/rest/internal/cleanup-policies` endpoint with the all-formats value `*`, checks for the `repository.cleanup` task Nexus schedules at every startup, and creates the `blobstore.compact` task through the Ext.Direct call `coreui_Task.create` the web UI uses. A deleted asset frees disk only after the `assetBlob.cleanup` task has soft-deleted its blob, which happens at the earliest an hour after the blob was written, and a compaction has removed it; `make cache-evict` exits non-zero when the blob store stays above its cap or lacks one of these tasks.

`make cache-status` prints one JSON object per cache, the build cache included, with `path`, `used_bytes`, `cap_bytes`, `headroom_bytes`, `cap_variable`, `atime_fallback` and `complete` (false when part of the cache was unreadable, as the root-owned registry mirror is from the host, or when no Docker engine answers for the build cache). It needs no running stack.

The roles [svc-registry-cache](../../../roles/svc-registry-cache/README.md) and [svc-cache-package](../../../roles/svc-cache-package/README.md) default to the same 30-day window through `max_idle_days` in their `meta/services.yml`, while their server size defaults stay: `blobstore_max: 40g`, and no size cap for the `registry` image. The `registry` image's `proxy.ttl` expires a blob a fixed time after it was cached, not after its last access, so on servers the window is an expiry.

## Activation 🎚️

The `cache` decision is exposed via `Profile.cache_stack_enabled()` in [profile.py](../../../cli/administration/deploy/development/profile.py). When active:

- [compose/cache.override.yml](../../../compose/cache.override.yml) is layered on top of the base [compose.yml](../../../compose.yml) by [compose.py](../../../cli/administration/deploy/development/compose.py) and [down.py](../../../cli/administration/deploy/development/down.py) via [common.py](../../../cli/administration/deploy/development/common.py)`compose_file_args`.
- The cache services are added.
- The runner's `infinito` service receives:
  - bind-mounts for the registry-cache CA, the package-cache client snippets (`pip.conf`, `npmrc`, `apt/${INFINITO_DISTRO}.list`), and the frontend CA file, plus the shared package cache folder when `INFINITO_CACHE_SHARED_HOST_PATH` is set
  - `extra_hosts` entries DNS-hijacking the HTTPS upstream hostnames to the frontend's static IP
  - `INFINITO_CACHE_PACKAGE_FRONTEND_IP` env var for the inner compose wrapper
- Cert generation, Nexus repo bootstrap, and runner trust-store install run from [compose.py](../../../cli/administration/deploy/development/compose.py).

When inactive, the override is omitted: cache services do not exist, the runner has no cache mounts or DNS-hijack, package managers go direct to upstream.

CI signals (`GITHUB_ACTIONS=true`, `INFINITO_RUNNING_ON_GITHUB=true`, `CI=true`) deactivate. Fresh runner disks per CI job give no cross-run amortization.

## Coverage Matrix 📋

| Traffic | Mechanism | Cached |
|---|---|---|
| Image pulls (any registry, inner `dockerd`) | `registry-cache` MITM via `HTTP_PROXY` env on `dockerd` | ✓ |
| `apt-get install` (Ansible task in runner) | `apt/${INFINITO_DISTRO}.list` URL-rewrite to `package-cache:8081` | ✓ |
| `pip install` (Ansible task in runner) | `pip.conf` URL-rewrite | ✓ |
| `npm install` (Ansible task in runner) | `.npmrc` URL-rewrite | ✓ |
| `gem`, `composer`, `go`, `curl https://…` (Ansible task in runner) | DNS-hijack + frontend HTTPS + runner CA-trust | ✓ |
| `pacman -S` (Ansible task in an arch runner or lab node) | read-only host cache + shared `pacman/` folder | ✓ |
| `pip`/`npm` local caches (runner) | shared `pip/` and `npm/` folders | ✓ |
| `RUN apt-get install` (inner Dockerfile build, Debian/Ubuntu) | `build.extra_hosts` DNS-hijack + frontend HTTP | ✓ |
| `RUN apk add` (inner Dockerfile build, Alpine ≤3.17 HTTP) | `build.extra_hosts` DNS-hijack + frontend HTTP | ✓ |
| `RUN pip/npm/gem/composer/go install` (inner Dockerfile build) | none today | ✗ |
| `RUN apk add` (Alpine ≥3.18 HTTPS) | none today | ✗ |
| App container runtime traffic (HTTPS to external API) | none today | ✗ |

The HTTPS-only inner-build gap requires per-image CA-trust bootstrap, which is out of scope for the current minimal-invasive design.

## Compose Wrapper Auto-Detection 🪄

The runner's `compose` wrapper at [roles/sys-svc-compose/files/python/compose.py](../../../roles/sys-svc-compose/files/python/compose.py) auto-detects compose files when invoked from per-app directories under `/opt/compose/<app>/`:

| File | When |
|---|---|
| `compose.yml` | always |
| `compose.override.yml` | when present (role provides it) |
| `compose.ca.override.yml` | when present (TLS self-signed CA-inject runs) |
| `compose.cache.override.yml` | generated on the fly when `INFINITO_CACHE_PACKAGE_FRONTEND_IP` is set; emits `build.extra_hosts` for every service that has a `build:` key |

[pull.py](../../../roles/sys-svc-compose/files/python/pull.py) delegates to the same wrapper so `pull` and `build --pull` operations see the identical `-f` set.

## Environment Variables 🌳

The host-side env-vars (`INFINITO_CACHE_REGISTRY_*`, `INFINITO_CACHE_PACKAGE_*`) are declared in [default.env](../../../default.env) and the dynamic ones (the Nexus memory sizing from `/proc/meminfo`, sha256 admin password) are computed by [utils/env/builder.py](../../../utils/env/builder.py). `make dotenv` writes them into `.env`, which Compose auto-loads and which `BASH_ENV` makes available to every Makefile recipe through [scripts/meta/env/load.sh](../../../scripts/meta/env/load.sh). See [variables.md](variables.md).

Per-variable defaults and purposes are in [compose.yml.md](../artefact/files/compose.yml.md) under the cache section.

`INFINITO_CACHE_PACKAGE_MAX_AGE_MIN` (default `8640` = 6 days) controls how long every Nexus proxy repo holds an upstream response before revalidating. The bootstrap helper applies it as `contentMaxAge`, `metadataMaxAge`, and `negativeCache.timeToLive`. The default is intentionally one day below the 7-day `Valid-Until` window Debian and Ubuntu generate in their apt `Release` files, so Nexus always refreshes the manifest before `apt-get update` would see it expired. Raise it for slow-moving upstreams when staleness is preferable to upstream load; lower it further for fast-moving feeds (`apt-debian-security`, branch-pinned tarballs) when staleness becomes visible.

## Docker Hub Login 🔑

`registry-cache` pulls from Docker Hub anonymously unless `INFINITO_CACHE_REGISTRY_AUTH` holds credentials; with them, its pulls count against your own Docker Hub account. The value reaches the proxy's `AUTH_REGISTRIES` unchanged, and empty keeps the anonymous pulls.

1. In Docker Hub, create a personal access token with the **Repo Public Read-only** permission and nothing more: every container that pulls through the cache pulls with this account.
2. In the primary checkout, which owns the cache stack (`INFINITO_CACHE_NETWORK` empty), add the token to [custom.env](../customize.md). A worktree that joins that stack ignores its own value.

   ```bash
   INFINITO_CACHE_REGISTRY_AUTH=auth.docker.io:<user>:<token>
   ```

   `<user>` is the Docker Hub username, not the email address. The host is `auth.docker.io`, not `registry-1.docker.io`: the proxy adds the credentials to the token requests it forwards to `auth.docker.io`.
3. Run `make dotenv`, then `make compose-up`. Compose recreates `infinito-registry-cache` because its environment changed; pulls through the cache fail until it is healthy again.
4. Check the login: `docker logs infinito-registry-cache 2>&1 | grep 'Adding Auth'` prints `Adding Auth for registry 'auth.docker.io' with user '<user>'.`, without the token.

To rotate the token, replace the value in `custom.env` and run `make dotenv` and `make compose-up` again, then revoke the old token in Docker Hub. To return to anonymous pulls, delete the line and run the same two commands.

The token lives in the untracked `custom.env` and `.env`. `docker compose config` and `docker inspect infinito-registry-cache` print it, so keep their output out of issues, chats and logs. An exported `INFINITO_CACHE_REGISTRY_AUTH` in your shell overrides `.env` in every `make` target, so set it only in `custom.env`.

## Operations 🛠️

| Action | Command |
|---|---|
| Start the stack with caches | `make compose-up` |
| Stop the stack | `make compose-down` |
| Pin the commit the stack serves and apply it (declarer only) | `make cache-declare ref=<commit>` |
| Install the pinned commit's `cache:` declarations into the running stack | `make cache-apply` |
| Evict idle and least recently used entries until every cache fits its cap | `make cache-evict` |
| Make the host's pacman or apt share the caches while `INFINITO_CACHE_HOST_SYNC` is `true`, or restore its files once it is `false` (runs `sudo`) | `make cache-host-sync` |
| Print used bytes, cap and headroom per cache as JSON on stdout, and the pinned and applied commit as JSON on stderr | `make cache-status` |
| Wipe local cache state | `make clean-cache` |
| Manually re-bootstrap Nexus repos | `bash roles/svc-cache-package/files/shell/bootstrap.sh` (after `make dotenv` or sourcing `scripts/meta/env/load.sh`) |
| Manually regenerate frontend certs | `bash roles/svc-cache-package/files/shell/certs.sh` |
| Regenerate every derived cache file | `make dotenv` |
| Reload nginx in the frontend | `docker exec infinito-package-cache-frontend nginx -s reload` |
| Inspect cache hits | `docker logs -f infinito-package-cache` and `docker logs -f infinito-package-cache-frontend` |

Cache state persists under `/var/cache/infinito/core/cache/`. Paths are configurable via the env scripts above.

## Vulnerability Databases 🔬

Every development stack and every swarm lab node mounts `INFINITO_VULNERABILITY_DB_HOST_PATH` read-only at `INFINITO_VULNERABILITY_DB_DIR`. A local deploy draws one engine and refreshes that engine's and Grype's database there once a day, under a lock file inside that directory, before the deploy starts; the stacks never download one. An act run binds the directory into its job container at the same path, and a refresh as root hands its files to the directory's owner. A CI deploy job points the variable at the databases it restored from the Actions cache instead. See [sys-ctl-hlth-runtime](../../../roles/sys-ctl-hlth-runtime/README.md).

## Adding a New Upstream ➕

When a new package manager or upstream needs caching:

Declare it under `cache:` in a `meta/networks.yml` and commit it. That file is the single point of truth; the Nexus repo, the leaf cert, the nginx server block, the `extra_hosts` entries, `pip.conf`, `.npmrc` and the apt sources are all derived from it. `make dotenv` renders the checkout's own client files; the shared stack serves only the declarations of one pinned commit.

The pin is the host file `INFINITO_CACHE_PIN_FILE` (`$XDG_STATE_HOME/infinito/cache.ref`). Only the declarer, the agent who owns the cache by order of the operator, moves it: `make cache-declare ref=<commit>` resolves the ref to a full commit, extracts that commit's committed state with `git archive` below `INFINITO_CACHE_PIN_ROOT/<sha>` (`$XDG_DATA_HOME/infinito/cache`), outside every checkout, prunes the checkouts of all earlier commits but the previous pin, and applies it; while the frontend is not running it only pins, and the owning checkout's next `make compose-up` applies the pin. `INFINITO_CACHE_PIN_ROOT` must be an absolute path outside the checkout, and an agent sandbox must allow writes below it and below the directory of `INFINITO_CACHE_PIN_FILE`. Materializing and applying hold a lock on `INFINITO_CACHE_PIN_ROOT/.lock`, and the apply reads the pin once the lock is held. `make cache-apply`, which `make compose-up` runs for every checkout, applies the same pinned checkout: it creates the Nexus proxy repositories, issues the frontend's leaf certificates, installs the pinned upstream map read-only onto the path the frontend mounts and reloads it. No checkout's working tree reaches the stack. A checkout's `compose.cache-consumer.yml` hijacks and apt sources name only the hosts the pinned commit declares identically; any other host keeps its real address, and while the configured pin cannot be read no host is hijacked there. Inner Dockerfile builds are not filtered yet: their `build.extra_hosts` still hijack every host in the checkout's own `INFINITO_CACHE_HOSTS` and `INFINITO_CACHE_HTTP_HOSTS`. `make cache-apply` refuses a frontend whose map lies outside `INFINITO_CACHE_PIN_ROOT`, as a frontend from before the pin or one an act container sees through the host daemon does; recreate it with `make compose-up` in the owning checkout. A checkout whose own declarations differ from the pin gets a line per differing repository or host and `ask the declarer to bump the pin`; its deploy continues. Without a pin, `make cache-apply` fails naming `make cache-declare`, the owning checkout's `make compose-up` fails before the cache services start, and a worktree's `make compose-up` warns and keeps the map already served. Recreate the checkout's runner with `make compose-up` after a bump so the new DNS hijacks reach it.

A host moves to the pin once, in this order:

1. Every checkout on the pin code runs `make dotenv-force` once from a fresh shell. It writes `INFINITO_CACHE_PIN_FILE` and `INFINITO_CACHE_PIN_ROOT` and moves `INFINITO_CACHE_PACKAGE_FRONTEND_CONF` below the pin root; until then `make cache-apply` exits with `INFINITO_CACHE_PIN_FILE is not set; run make dotenv`. [load.sh](../../../scripts/meta/env/load.sh) lets an exported value win over `.env`, so a shell that still exports the old `INFINITO_CACHE_PACKAGE_FRONTEND_CONF` keeps the in-checkout path, and every apply from it refuses the frontend.
2. The declarer runs `make cache-declare ref=<merge commit>` once. The running frontend still mounts the primary checkout's `compose/package-cache-frontend/upstreams.conf`, outside the pin root, so the pin is written and the apply refuses, naming that mount.
3. The next `make compose-up` of the owning checkout recreates the frontend on the map below the pin root. From then on the primary checkout's `compose/package-cache-frontend/upstreams.conf` is unused and may be deleted.
4. A worktree still on older code keeps running its own apply: its copy onto the read-only map fails, the frontend keeps the pinned map, and its deploy continues with the warning it already prints.

A TLS upstream only reaches an inner image build when that build trusts the frontend's CA: the compose wrapper hands a build the plain-HTTP hosts by default and the full host list only when its Dockerfile runs `package-frontend-ca.sh` (see [svc-ai-ltengine](../../../roles/svc-ai-ltengine/files/Dockerfile) for the three lines and the two staging tasks that go with them).

Put the declaration in the role that needs the upstream. An upstream no single role owns goes in [svc-cache-package](../../../roles/svc-cache-package/meta/networks.yml).

```yaml
cache:
  repos:
    raw-example:
      flavor: raw
      upstream: https://example.org/
  hosts:
    example.org:
      repo: raw-example
```

A repository is proxied by Nexus. A host is additionally answered for by the frontend, so a client keeps addressing its real upstream URL. `ports: ["80"]` serves it over plain HTTP and issues no certificate; `paths:` maps several repositories under one host; `mirror:` on a repository names the sibling the frontend retries against on `502`, `503` or `504`; `passthrough: true` suits an upstream that hands out URLs already carrying the repository prefix.

A deployed host may correct or extend any of this from its inventory under `applications.svc-cache-package.repos` and `.upstreams`; the dev stack has no inventory and uses the declarations unchanged.

### Pinned Artefacts 📌

A file a role downloads whole, a model weight above all, is declared under `cache: artefacts:` in the `meta/networks.yml` of any one role. This section is the contract the skills orchestrator image, the security check and the store consume; [artefacts.py](../../../utils/cache/artefacts.py) implements it and the lint [test_cache_artefacts_pinned.py](../../../tests/lint/ansible/roles/meta/test_cache_artefacts_pinned.py) enforces it over every role.

```yaml
cache:
  artefacts:
    example-model:
      url: https://huggingface.co/<org>/<repo>/resolve/<commit>/<file>
      revision: "<commit>"
      sha256: "<64 lowercase hex digits>"
      bytes: "807690688"
```

The three pins are double-quoted, because the bootstrap reader of `meta/networks.yml` refuses a plain scalar that starts with a digit. A `url` with `~` is double-quoted too, because a plain scalar of that reader starts with a letter, `_` or `/` and holds only letters, digits, spaces and `_./+@:-`.

- The name matches `[a-z0-9][a-z0-9._-]*` and is declared by one role only. The collection compares whole declarations, the declaring role included, so a second role declaring the name fails it naming both roles, even with identical keys. The url, not the declaring role, ties an artefact to its repository.
- The `artefacts:` section and every entry in it are mappings, and an entry carries only the keys `url`, `revision`, `sha256` and `bytes`; any other shape or key is a contract breach, not an empty declaration.
- `url` is the absolute `https` URL of exactly one upstream file at the pinned revision. Its path holds only `A-Z a-z 0-9 . _ ~ / -` and no empty or all-dot segment (`.`, `..`). It carries no `%` anywhere, no query, no fragment, no userinfo, no port and no whitespace, because it ends up in shell lines and Dockerfiles.
- `url` resolves to exactly one repository: the one whose `upstream` is its longest prefix ending at a segment, so the prefetch knows which Nexus repository holds it; two repositories with that same upstream refuse it. An `https` url reaches its host's TLS listener, which routes every path to that host's repository: its `repo`, else the repository of its first `paths:` route, because `paths:` routes serve the plain-HTTP listeners only. So the url's host is declared under `cache: hosts:` with `443` among its `ports` (the default), its repository is this repository, and that repository's upstream is the host's root, so `<base>/<host>/<path>` reaches the same file through the same repository.
- `revision` is a 40-digit lowercase hex commit, because branches and tags move, and sits in the segment where the host keeps the ref. On `huggingface.co` that is the segment after `resolve` in `<org>/<repo>/resolve/<commit>/<file>`, optionally under `datasets/` or `spaces/`, with org, repo and file present and `resolve` once. On `raw.githubusercontent.com` it is the third segment of `<owner>/<repo>/<commit>/<file>`. A host with no known layout is refused.
- `sha256` is the 64-digit lowercase hex digest of the file's bytes, and `bytes` its exact size as a positive decimal integer without a leading zero. One digest declared with two sizes is refused; two names may carry one digest, and the store then holds that file once.

A consumer fetches `<base>/<host>/<path>`, where `<host>` is the url's host and `<path>` its path without the leading slash. The base is an `http` or `https` URL of a host with an optional port from 1 to 65535 and an optional path prefix, without a trailing slash, whitespace, `%`, userinfo, query or fragment; the value `https:/` makes the expression the url itself, an empty base makes `url_for` and `records` keep the upstream, and both refuse any other shape. Core reads the base bare, as `${INFINITO_ARTEFACT_BASE}`: [default.env](../../../default.env) declares the key with the value `https:/`, and `make dotenv` replaces it with `http://<INFINITO_CACHE_PACKAGE_FRONTEND_IP>` while `INFINITO_CACHE_STACK` is true ([artefact_base.py](../../../utils/env/handlers/infinito/cache/artefact_base.py)); an exported value or a line in `custom.env` wins. The frontend answers `/<host>/<path>` on its port 80 `default_server` for every host with a TLS listener and proxies it to the repository that listener serves. A consumer outside core reads no `default.env` and writes `${INFINITO_ARTEFACT_BASE:-https:/}`.

A consumer verifies the sha256 of what it fetched and fails on a mismatch; it never accepts a different file. A matching digest pins the size too, so in a Dockerfile `ADD --checksum=sha256:<sha256>`, which checks the digest only, is enough; `bytes` feeds the store's size accounting. A consumer may retry the upstream when the base does not answer or answers 5xx.

## Background 📚

- Compose-file env-var contract: [compose.yml.md](../artefact/files/compose.yml.md)
- Profile gating mechanics: [profile.py](../../../cli/administration/deploy/development/profile.py)
