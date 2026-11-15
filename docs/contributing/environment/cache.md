# Local Caches 📦

Three local cache services and one shared cache folder accelerate re-deploys, reduce upstream traffic, and harden the development workflow against transient upstream outages. The three services run once per machine inside the [infra runner](#infra-runner-), and every checkout consumes them; no checkout starts a cache service of its own. They are gated together by [profile.py](../../../cli/administration/deploy/development/profile.py), see [Activation](#activation-). Every cache has a fixed size cap and an idle window, see [Bounds and Eviction](#bounds-and-eviction-).

## Stack Kinds 🧱

[stacks.yml](../../../compose/stacks.yml) declares every local stack and the targets that reach it.

| Stack | Class | Runs in | Started by |
|---|---|---|---|
| `cache` | always-on | the infra runner | `make infra-up`, which `make compose-up` runs first |
| `tools` | on-demand | the infra runner | `make i18n-translate`, `make i18n-tune` and `make test-oracle` |
| `test-runner` | long-lived | the shared test runner `infinito-test-<hash>` | the first `make test*` or `make lint*` call, see [variables.md](variables.md) |
| `deploy` | on-demand | the checkout's own deploy stack | `make compose-up` |

## Infra Runner 🏗️

One infra runner per machine hosts the caches and, on demand, the tools. It is the service `runner` of the compose project `infinito-infra` ([infra.yml](../../../compose/infra.yml)), a privileged systemd container of the local toolchain image, named by `INFINITO_INFRA_RUNNER_CONTAINER` (default `infinito-infra-runner`).

- **Network:** the runner owns the network `infinito-infra` on `INFINITO_INFRA_SUBNET` (default `10.47.0.0/24`, outside `172.30.0.0/16` and Docker's default address pools) and sits at host `.2` of it, `INFINITO_INFRA_RUNNER_IP`.
- **Aliases:** `infinito-registry-cache`, `infinito-package-cache`, `infinito-package-cache-frontend` and `infinito-translate` all resolve to the runner. `make dotenv` writes the runner address into `INFINITO_CACHE_REGISTRY_IP`, `INFINITO_CACHE_PACKAGE_IP` and `INFINITO_CACHE_PACKAGE_FRONTEND_IP`, so every checkout carries the same three values.
- **Consumers:** every deploy stack and the shared test runner join `infinito-infra` and reach the caches and the tools by name. `make worktree-up` writes no cache network and no cache address.
- **Mounts:** the roots of `INFINITO_WORKTREE_ROOTS` (colon-separated absolute directories; empty: the primary checkout and `~/.local/share/worktrees`) are mounted read-only at their host paths through the generated override `build/compose/infra-roots.override.yml`. The cache base `DIR_CACHE` (`/var/cache/infinito/core/cache`) is bound read-write at its host path, `INFINITO_INFRA_CACHE_DIR`. Everything else the runner writes goes to its own volumes `docker` and `var-lib`.
- **Ports:** only the gateway port `INFINITO_TOOLS_TRANSLATE_PORT` is published, on `127.0.0.1`. The caches answer on the infra network only.

The lifecycle targets, all implemented in [infra.py](../../../utils/infra.py):

- `make infra-up` first checks the disk floor `INFINITO_CACHE_DISK_FLOOR` and exits with status 2 before anything starts when `free + used - sum(caps)` is below it, naming every cap variable. It refuses a checkout outside the worktree roots and names `make infra-update`. It also exits with status 2 while a container of the legacy per-checkout cache stack (`infinito-registry-cache`, `infinito-package-cache`, `infinito-package-cache-frontend`) runs on the host, or when `docker ps` cannot answer, because the runner takes over the same cache base. `make infra-up takeover=true` stops those containers instead, with `docker stop -t 120` inside the machine lock right after the owner marker, once every other check passed, and recreates a runner that already runs; it still refuses while `docker ps` cannot answer. When the host Docker daemon's `HTTPSProxy` or `HTTPProxy` names the address of the running legacy `infinito-registry-cache`, as on a host that pulled through it at `172.30.0.6:3128`, the takeover records that network and address in `<DIR_CACHE>/infra.bridge`, and every later call joins the runner to that network at that address through `build/compose/infra-bridge.override.yml`, so the daemon keeps pulling through the same CA without a restart. Delete `<DIR_CACHE>/infra.bridge` and run `make infra-update` once the daemon's proxy names the runner address. If anything after the stop fails, the same call stops the runner, starts the legacy containers again and removes `infra.owner` and `infra.bridge` before it exits non-zero. It refuses the same way while the calling user cannot write `<DIR_CACHE>` itself, which Docker creates as root on a machine that ran the legacy stack, and names the one-time step: `sudo chown "$USER": <DIR_CACHE>` for that directory alone, or `sudo install -d -o "$USER" <DIR_CACHE>` when it is missing. Only after the runner is up does it write the idle units under `<DIR_CACHE>/infra/systemd`, so a refusal writes nothing. Otherwise it takes the machine lock `<DIR_CACHE>/infra.lock`, writes the owner marker `<DIR_CACHE>/infra.owner` before anything starts, starts the runner unless it already runs, and inside it provisions the inventory `~/inventories/infinito-infra` with `svc-registry-cache` (flavor `multi-proxy`) and `svc-cache-package` from host vars rendered out of [infra.yml.j2](../../../inventories/development/infra.yml.j2), with the caps and the idle window taken from the environment. It then deploys both roles, links and enables the tools idle timer inside the runner and runs `make cache-evict`. A call while the runner already runs changes nothing.
- `make infra-update` runs the same steps against a running runner, so changed caps, worktree roots or image take effect.
- `make infra-down` stops the runner under the same lock. Its volumes, every cache byte and the owner marker stay.
- The owner marker `<DIR_CACHE>/infra.owner` tells a checkout that still layers the legacy cache stack that the cache base belongs to the infra runner, so it deploys without the legacy stack instead of starting a second Nexus on the same data.
- `make infra-status` prints one JSON object: the container name, whether it runs, its address, the gateway URL `http://127.0.0.1:<INFINITO_TOOLS_TRANSLATE_PORT>` that `make i18n-translate gateway=` takes, and per tools project whether it is addressable inside the runner.

The tools (LibreTranslate, LiteLLM, Ollama, System One and the `web-svc-translate` gateway) deploy into the same runner on demand and stop once `INFINITO_TOOLS_IDLE_GRACE` has passed since the last tools target ended, see [web-svc-translate](../../../roles/web-svc-translate/README.md). `make i18n-pause` and `make i18n-resume` pause and resume only the tools projects; the caches keep answering.

## Cache Interface 🔌

Every consumer, the store and peer repositories included, reaches the caches through these names and files and through nothing else.

| Interface | Address or path | How a consumer uses it |
|---|---|---|
| Registry mirror | `http://infinito-registry-cache:3128` on the network `infinito-infra` | `HTTP_PROXY` and `HTTPS_PROXY` of the consumer's `dockerd`, set by [proxy.conf](../../../compose/registry-cache/proxy.conf) |
| Registry mirror CA | `ca.crt` in `INFINITO_CACHE_REGISTRY_CA_HOST_PATH` (`<DIR_CACHE>/registry/ca`) | mounted read-only at `/opt/registry-cache-ca` and trusted by [registry-ca.sh](../../../scripts/docker/cache/registry-ca.sh) before `dockerd` starts |
| Package cache | `http://infinito-package-cache:8081` | Nexus repository URLs `/repository/<repo>/` and its REST API |
| Package cache frontend | `infinito-package-cache-frontend`: HTTPS on 443 per upstream hostname, plain HTTP on 80 | `extra_hosts` entries that map every upstream hostname to `INFINITO_CACHE_PACKAGE_FRONTEND_IP`, so a client keeps its real upstream URL |
| Frontend CA | `INFINITO_CACHE_PACKAGE_FRONTEND_CA_FILE` (`<DIR_CACHE>/package/frontend/ca/ca.crt`) | mounted read-only at `/opt/package-frontend-ca.crt` and trusted by [ca.sh](../../../roles/svc-cache-package/files/shell/ca.sh) |
| Artefact base | `INFINITO_ARTEFACT_BASE` (`http://<INFINITO_CACHE_PACKAGE_FRONTEND_IP>` while `INFINITO_CACHE_STACK` is true) | `<base>/<host>/<path>` for a [pinned artefact](#pinned-artefacts-) |

The generated `compose.cache-consumer.yml`, rendered from [cache-consumer.yml.jinja](../../../compose/templates/cache-consumer.yml.jinja), is the consumer wiring of a deploy stack's `infinito` service and holds every mount and host entry of the table.

## Services 🧩

### Registry Cache 🐳

[svc-registry-cache](../../../roles/svc-registry-cache/README.md) runs `rpardini/docker-registry-proxy` in its `multi-proxy` flavor inside the infra runner and transparently MITMs every Docker image pull of a consumer's inner `dockerd` through `infinito-registry-cache:3128`, regardless of upstream registry (`docker.io`, `ghcr.io`, `mcr.microsoft.com`, …). The consumer trusts the proxy CA via [registry-ca.sh](../../../scripts/docker/cache/registry-ca.sh).

Pulls only. Pushes are not intercepted.

### Package Cache 📚

[svc-cache-package](../../../roles/svc-cache-package/README.md) runs `sonatype/nexus3` inside the infra runner as `infinito-package-cache` and exposes pull-through proxies for package-manager downloads:

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

Every apt repository exists twice, once per upstream mirror. Each one serves every suite of the archive it proxies, not only its `distribution`: [bootstrap.sh](../../../roles/svc-cache-package/files/shell/bootstrap.sh) sets `enforceDistribution` to `false` on every create and update, since `true` answers every other suite with `404`. Nexus has no group repository type for `apt` (only maven, raw, docker, yum, npm, pypi, rubygems, go and friends), so the failover lives in the frontend: a request that the primary repo answers with `502`/`503`/`504` is re-run against the `-mirror` repo, which proxies a different host. `404` deliberately does not retry, because a missing file is missing on both mirrors and apt probes for missing files often. The frontend waits at most 8 s for a primary before it re-runs the request against the mirror; the `-mirror` locations keep the global 300 s.

Bootstrap is idempotent and runs from [bootstrap.sh](../../../roles/svc-cache-package/files/shell/bootstrap.sh) once Nexus is healthy. It loops over `INFINITO_CACHE_UPSTREAMS` and holds no repository of its own.

### Package Cache Frontend 🔐

The frontend of [svc-cache-package](../../../roles/svc-cache-package/README.md) runs `nginx:alpine` inside the infra runner as `infinito-package-cache-frontend` and reverse-proxies upstream package-manager hostnames onto the matching Nexus repo path. Combined with `extra_hosts` DNS-hijack on consumers, package managers can hit their real upstream URL and still flow through the cache.

Two listener layers:

- HTTPS (port 443): per-hostname server certs signed by a dedicated CA. Used by the deploy stack's `infinito` container (Ansible-driven `pip install`, `gem install`, `composer install`, `curl https://…`), which trusts the CA via [ca.sh](../../../roles/svc-cache-package/files/shell/ca.sh).
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

- Compose slots: `compose_file_args` layers [compose/shared-cache.override.yml](../../../compose/shared-cache.override.yml) when the caches are [active](#activation-) and the variable is set. It mounts the folder and `pacman.sh` into the deploy stack's `infinito` container and sets `PIP_CACHE_DIR` and `npm_config_cache`. `make compose-up` then runs `pacman.sh` in that container.
- Swarm lab nodes: `01_bootstrap.sh` layers [compose/swarm/shared-cache.override.yml](../../../compose/swarm/shared-cache.override.yml) next to the cache override when the variable is set. It mounts the folder and `pacman.sh` into the manager, both workers, the NFS server and the backup host, and [playbook.yml](../../../compose/swarm/playbook.yml) runs `pacman.sh` on each node that has it.
- Act job containers: [workflow.sh](../../../scripts/tests/deploy/act/workflow.sh) wires the folder under the condition `01_bootstrap.sh` uses for the swarm lab nodes, a set variable and an existing `infinito-package-cache-frontend` container. It mounts the folder into every job container it starts, sets `PIP_CACHE_DIR` and blanks `cache: pip` in the copy of the workflow it hands to act, so `actions/setup-python` neither archives the folder after a job nor extracts an old archive into it, and the `make install-force` of each job reuses the wheels the host already downloaded. The deploy workflows on GitHub runners never call the wrapper. The workspace suite ([call-test-workspace.yml](../../../.github/workflows/call-test-workspace.yml)) does, through `make swarm-zombie`, and there too the act jobs get the folder exactly when the lab nodes of the same run get it: whenever the suite's own cache stack is up at that point.
- Core Playwright runs take their browsers from the `mcr.microsoft.com/playwright` image, so they leave `ms-playwright/` empty.

pacman on an arch stack reads up to three cache directories. `INFINITO_CACHE_HOST_PACMAN_PATH`, written by [pacman_path.py](../../../utils/env/handlers/infinito/cache/host/pacman_path.py), is the first `CacheDir` of the host's `pacman-conf`, and only on a host whose `/etc/os-release` `ID` is exactly `arch` running an arch stack. On Manjaro, EndeavourOS and every other host, and on every stack that does not run pacman, the variable is empty and pacman uses the shared layer alone. When it is set, [compose/pacman.override.yml](../../../compose/pacman.override.yml) and [compose/swarm/pacman.override.yml](../../../compose/swarm/pacman.override.yml) mount it read-only at the same path, layered only together with the shared folder. `pacman.sh` lists it as the first `CacheDir`, the node's own download directory `<shared>/pacman/node-XXXXXX/` as the second and `<shared>/pacman/` as the third. `pacman.sh` creates the node download directory with `mktemp` on its first run and reuses the one already listed in `pacman.conf` on every later run. pacman finds a package in any of the three directories and downloads a missing one, `.part` file included, into the node download directory, the first one it can write. The `PostTransaction` hook `pacman.sh` writes to `pacman.d/hooks/infinito-shared-cache.hook` beside `pacman.conf` then renames every finished package and signature from the node download directory into `<shared>/pacman/` and leaves `.part` files there for the next resume. `pacman.sh` fails when `pacman.conf` sets `HookDir`. The disc-space cleanup runs `pacman -Sc` per writable `CacheDir`, so it never touches the read-only layer.

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
- On a Debian or Ubuntu host, every `deb` entry of `/etc/apt/sources.list`, `/etc/apt/sources.list.d/*.list` and `/etc/apt/sources.list.d/*.sources` whose archive an `apt-*` repository of the package cache proxies gets a copy pointing at `http://<INFINITO_CACHE_PACKAGE_REST_HOST>:<INFINITO_CACHE_PACKAGE_PORT>/repository/<repo>/`, the Nexus port the infra runner publishes on loopback only, inserted before it with every option, `Signed-By` included. A host that is a subdomain of such an archive's host with the same path, such as `us.archive.ubuntu.com`, counts as that archive. Each suite goes to the repository of its pocket, the part after the codename (`trixie-security` to the archive's `-security` repository), else to the archive's release repository; a suite with neither stays. A repository and suite take copies from one archive only, the first apt reads, since apt refuses one suite with two `Signed-By` values. A deb822 stanza gets one copy per repository, holding every suite routed there. The original stays behind the copy, so `apt-get` falls back to it while the stack is down; python-apt, and with it Ansible's `apt` module with `update_cache`, fails on the unreachable copy instead. Third-party repositories, disabled stanzas, entries that set `trusted`, `allow-insecure`, `allow-weak` or `allow-downgrade-to-insecure` to anything but `no`, `false`, `without`, `off`, `disable` or `0`, and HTTPS entries the cache would fetch over HTTP stay as they are. `/etc/apt/apt.conf.d/99infinito-cache-host-sync` sets `APT::Keep-Downloaded-Packages "false"`, so Nexus holds the one copy of each package.
- Before anything is written, `pacman-conf` reads the planned `pacman.conf`, or `apt-get update` fetches the planned entries alone, with `APT::Update::Error-Mode=any` so a transient network error fails it too. When it refuses, every file stays as it was.
- The original and the digest of every changed file go to `<DIR_VAR_LIB>/cache-host-sync/`, on a Debian or Ubuntu host with the digest of every other source file and the repository URLs a copy can point at. A rerun restores them first and plans again.

With `false`, the target restores every recorded file that nothing changed since the sync byte for byte and removes the drop-in it created. On an Arch host it restores nothing while `pacman.conf` changed since the sync, and names it and the original it keeps. On a Debian or Ubuntu host it names every recorded file changed since the sync and leaves it in place. Then every source file, and every `.bak` backup `apt modernize-sources` leaves, that holds neither what the sync left there nor its bytes from before the sync loses each `deb` and `deb-src` entry and each URI that points at a repository the sync could copy to; a stanza left without a URI goes, while its comments stay. A release upgrade or `apt modernize-sources` after the sync therefore never blocks the revert. Any other host `ID` with `true` is refused.

## Bounds and Eviction 📏

Every cache has a fixed cap and the idle window `INFINITO_CACHE_MAX_IDLE_DAYS` (default `30`): an entry without access for that many days is evicted. `make dotenv` writes the defaults below from [default.env](../../../default.env); an exported value or a line in [custom.env](../customize.md) wins, and no value depends on the free disk space.

| Cache | Path | Cap variable | Default | Age eviction | Size eviction |
|---|---|---|---|---|---|
| Registry mirror | `INFINITO_CACHE_REGISTRY_HOST_PATH` | `INFINITO_CACHE_REGISTRY_MAX_SIZE` | `40g` | nginx `proxy_cache_path inactive=<idle window>d`, set by the `multi-proxy` entrypoint of [svc-registry-cache](../../../roles/svc-registry-cache/README.md) | the nginx cache manager evicts the least recently used blobs above `max_size` |
| Nexus | `INFINITO_CACHE_PACKAGE_HOST_PATH` | `INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX` | `20g` | the cleanup policy `infinito-idle` (last downloaded before the idle window) on every proxy repository, run daily at 01:00 by the `Cleanup service` task Nexus creates itself, followed by the daily compaction of the `default` blob store at 02:00 UTC that the bootstrap schedules | `make cache-evict` runs the cleanup, the unused asset blob cleanup and the compaction, then deletes the least recently downloaded assets and repeats the last two until the blob store is at or below the cap |
| Shared folders | `INFINITO_CACHE_SHARED_HOST_PATH` (pip, npm, pacman, ms-playwright together) | `INFINITO_CACHE_SHARED_MAX_SIZE` | `10g` | `make cache-evict` removes files without access in the idle window | then the least recently accessed files, until all shared folders together are at or below the one cap |
| Models | `INFINITO_TOOLS_MODELS_HOST_PATH` | `INFINITO_TOOLS_MODELS_MAX_SIZE` | `30g` | `make cache-evict` removes model units without use in the idle window | then the least recently used units, until the folder is at or below the cap |
| Host build cache | the host Docker daemon's BuildKit store | `INFINITO_BUILD_CACHE_MAX_SIZE` | `20g` | none | every image build of [build.sh](../../../scripts/image/build.sh) ends with [prune.sh](../../../scripts/image/prune.sh), a `docker builder prune` that keeps at most the cap |

The sweeper of the shared folders and the models removes related files together: an npm `_cacache` index bucket with the content files only it references, a pip `http-v2` entry with its `.body`, a pacman package with its `.sig`, and a Playwright browser directory as a whole; `ms-playwright/.links` stays. A model unit is a whole package directory or file below a tool's folder (`models/libretranslate/<package>`), or an Ollama manifest together with the blobs no other manifest references; the sweeper skips the models folder while a running container mounts it. A store entry `models/<sha256>` of a [pinned artefact](#pinned-artefacts-) that the calling checkout or the pinned commit declares is never evicted, whatever its age and the cap; while the pinned commit's declarations cannot be read, the sweeper skips the models folder and says so. It never removes a cache root, a directory that is not a unit, or anything outside the cache paths. On a filesystem mounted `noatime` it reads the modification time instead of the access time, and `make cache-status` reports `atime_fallback: true` for that cache.

The prune flag that keeps a storage amount changed its name between Docker releases: [prune.sh](../../../scripts/image/prune.sh) uses `--max-used-space` when `docker builder prune --help` lists it, else `--keep-storage`, and fails the build when the engine offers neither.

`make cache-evict` first checks the disk floor `INFINITO_CACHE_DISK_FLOOR` (default `15g`): the caps fit the machine only when `free + used - sum(caps)` reaches it. Otherwise it exits non-zero before it evicts anything and names every cap variable. It then sweeps the shared folders and the models and evicts the Nexus blob store through its REST API, and prints one status line per cache. Its first run on a cache above its cap is the migration: the same age and size eviction, so entries accessed inside the idle window stay as far as the cap allows and no cache directory is removed or recreated. `make clean-cache` keeps its wipe semantics and is called by no other target.

The pinned Nexus Community Edition has no public API for cleanup policies or for creating tasks. The [bootstrap](../../../roles/svc-cache-package/files/shell/bootstrap.sh) therefore writes the policy through the internal `/service/rest/internal/cleanup-policies` endpoint with the all-formats value `*`, checks for the `repository.cleanup` task Nexus schedules at every startup, and creates the `blobstore.compact` task through the Ext.Direct call `coreui_Task.create` the web UI uses. A deleted asset frees disk only after the `assetBlob.cleanup` task has soft-deleted its blob, which happens at the earliest an hour after the blob was written, and a compaction has removed it; `make cache-evict` exits non-zero when the blob store stays above its cap or lacks one of these tasks.

`make cache-status` prints one JSON object per cache, the build cache included, with `path`, `used_bytes`, `cap_bytes`, `headroom_bytes`, `cap_variable`, `atime_fallback` and `complete` (false when part of the cache was unreadable, as the root-owned registry mirror is from the host, or when no Docker engine answers for the build cache). It needs no running stack.

The roles [svc-registry-cache](../../../roles/svc-registry-cache/README.md) and [svc-cache-package](../../../roles/svc-cache-package/README.md) default to the same 30-day window through `max_idle_days` in their `meta/services.yml`, while their server size defaults stay: `blobstore_max: 40g`, and no size cap for the `registry` image. The `registry` image's `proxy.ttl` expires a blob a fixed time after it was cached, not after its last access, so on servers the window is an expiry. Inside the infra runner, the host vars rendered from [infra.yml.j2](../../../inventories/development/infra.yml.j2) set `max_idle_days` of both roles to `INFINITO_CACHE_MAX_IDLE_DAYS` and `blobstore_max` to `INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX`.

## Activation 🎚️

The `cache` decision is exposed via `Profile.cache_stack_enabled()` in [profile.py](../../../cli/administration/deploy/development/profile.py): `INFINITO_CACHE_STACK` decides when it is `true` or `false`; without it, the CI signals (`GITHUB_ACTIONS=true`, `INFINITO_RUNNING_ON_GITHUB=true`, `CI=true`) deactivate, because fresh runner disks per CI job give no cross-run amortization. When active:

- `make compose-up` runs `make infra-up` first, so the caches answer before the deploy stack starts.
- The deploy stack and the shared test runner join the network `infinito-infra`.
- The deploy stack's `infinito` service receives the wiring of the generated `compose.cache-consumer.yml` ([cache-consumer.yml.jinja](../../../compose/templates/cache-consumer.yml.jinja)):
  - bind-mounts for the registry-cache CA, the package-cache client snippets (`pip.conf`, `npmrc`), and the frontend CA file, plus the shared package cache folder when `INFINITO_CACHE_SHARED_HOST_PATH` is set
  - `extra_hosts` entries DNS-hijacking the HTTPS upstream hostnames to the runner address in `INFINITO_CACHE_PACKAGE_FRONTEND_IP`
  - `INFINITO_CACHE_PACKAGE_FRONTEND_IP` env var for the inner compose wrapper
- Cert generation and the Nexus repo bootstrap run in the `svc-cache-package` deploy inside the infra runner; the consumer installs both CAs into its own trust store.

With `INFINITO_CACHE_STACK=false`, no target starts the infra runner, renders the infra inventory or attaches to the infra network. The deploy stack has no cache mounts or DNS-hijack, and package managers go direct to upstream.

## Coverage Matrix 📋

| Traffic | Mechanism | Cached |
|---|---|---|
| Image pulls (any registry, inner `dockerd`) | registry cache MITM via `HTTP_PROXY` env on `dockerd` | ✓ |
| `apt-get install` (Ansible task in runner) | `extra_hosts` DNS-hijack of the stock sources + frontend HTTP | ✓ |
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

The host-side env-vars (`INFINITO_CACHE_REGISTRY_*`, `INFINITO_CACHE_PACKAGE_*`, `INFINITO_INFRA_*`) are declared in [default.env](../../../default.env) and the dynamic ones (the runner address and the three cache addresses derived from it, the Nexus memory sizing from `/proc/meminfo`, sha256 admin password) are computed by [utils/env/builder.py](../../../utils/env/builder.py). `make dotenv` writes them into `.env`, which Compose auto-loads and which `BASH_ENV` makes available to every Makefile recipe through [scripts/meta/env/load.sh](../../../scripts/meta/env/load.sh). See [variables.md](variables.md).

Per-variable defaults and purposes are in [compose.yml.md](../artefact/files/compose.yml.md) under the cache section.

`INFINITO_CACHE_PACKAGE_MAX_AGE_MIN` (default `8640` = 6 days) controls how long every Nexus proxy repo holds an upstream response before revalidating. The bootstrap helper applies it as `contentMaxAge`, `metadataMaxAge`, and `negativeCache.timeToLive`. The default is intentionally one day below the 7-day `Valid-Until` window Debian and Ubuntu generate in their apt `Release` files, so Nexus always refreshes the manifest before `apt-get update` would see it expired. Raise it for slow-moving upstreams when staleness is preferable to upstream load; lower it further for fast-moving feeds (`apt-debian-security`, branch-pinned tarballs) when staleness becomes visible.

## Docker Hub Login 🔑

The registry cache pulls from Docker Hub anonymously unless `INFINITO_CACHE_REGISTRY_AUTH` holds credentials; with them, its pulls count against your own Docker Hub account. The value reaches the proxy's `AUTH_REGISTRIES` unchanged, and empty keeps the anonymous pulls.

1. In Docker Hub, create a personal access token with the **Repo Public Read-only** permission and nothing more: every container that pulls through the cache pulls with this account.
2. Add the token to [custom.env](../customize.md) of the checkout you run the infra targets from. The infra runner exists once per machine, so one value serves every checkout.

   ```bash
   INFINITO_CACHE_REGISTRY_AUTH=auth.docker.io:<user>:<token>
   ```

   `<user>` is the Docker Hub username, not the email address. The host is `auth.docker.io`, not `registry-1.docker.io`: the proxy adds the credentials to the token requests it forwards to `auth.docker.io`.
3. Run `make dotenv`, then `make infra-update`. The registry cache restarts with the changed environment; pulls through the cache fail until it is healthy again.
4. Check the login: the registry cache's log inside the infra runner prints `Adding Auth for registry 'auth.docker.io' with user '<user>'.`, without the token.

To rotate the token, replace the value in `custom.env` and run `make dotenv` and `make infra-update` again, then revoke the old token in Docker Hub. To return to anonymous pulls, delete the line and run the same two commands.

The token lives in the untracked `custom.env` and `.env` and in the registry cache's environment inside the infra runner. Inspecting that container or rendering its compose configuration prints it, so keep such output out of issues, chats and logs. An exported `INFINITO_CACHE_REGISTRY_AUTH` in your shell overrides `.env` in every `make` target, so set it only in `custom.env`.

## Operations 🛠️

| Action | Command |
|---|---|
| Start the infra runner with the caches (`make compose-up` runs it first) | `make infra-up` |
| Apply changed caps, worktree roots or image to the running infra runner, which re-runs the Nexus bootstrap and the frontend certs | `make infra-update` |
| Stop the infra runner and keep every cache byte | `make infra-down` |
| Print the runner's state, address, gateway URL and addressable tools projects as JSON | `make infra-status` |
| Stop this checkout's deploy stack; the infra runner keeps running | `make compose-down` |
| Pin the commit the caches serve and apply it (declarer only) | `make cache-declare ref=<commit>` |
| Install the pinned commit's `cache:` declarations into the running caches | `make cache-apply` |
| Evict idle and least recently used entries until every cache fits its cap | `make cache-evict` |
| Make the host's pacman or apt share the caches while `INFINITO_CACHE_HOST_SYNC` is `true`, or restore its files once it is `false` (runs `sudo`) | `make cache-host-sync` |
| Print used bytes, cap and headroom per cache as JSON on stdout, and the pinned and applied commit as JSON on stderr | `make cache-status` |
| Wipe local cache state | `make clean-cache` |
| Regenerate every derived cache file | `make dotenv` |

Cache state persists under `DIR_CACHE` (`/var/cache/infinito/core/cache/`), which the infra runner binds at its host path. Paths are configurable via the env scripts above.

## Vulnerability Databases 🔬

Every development stack and every swarm lab node mounts `INFINITO_VULNERABILITY_DB_HOST_PATH` read-only at `INFINITO_VULNERABILITY_DB_DIR`. A local deploy draws one engine and refreshes that engine's and Grype's database there once a day, under a lock file inside that directory, before the deploy starts; the stacks never download one. An act run binds the directory into its job container at the same path, and a refresh as root hands its files to the directory's owner. A CI deploy job points the variable at the databases it restored from the Actions cache instead. See [sys-ctl-hlth-runtime](../../../roles/sys-ctl-hlth-runtime/README.md).

## Adding a New Upstream ➕

When a new package manager or upstream needs caching:

Declare it under `cache:` in a `meta/networks.yml` and commit it. That file is the single point of truth; the Nexus repo, the leaf cert, the nginx server block, the `extra_hosts` entries, `pip.conf`, `.npmrc` and the apt sources are all derived from it. `make dotenv` renders the checkout's own client files; the shared stack serves only the declarations of one pinned commit.

The pin is the host file `INFINITO_CACHE_PIN_FILE` (`$XDG_STATE_HOME/infinito/cache.ref`). Only the declarer, the agent who owns the cache by order of the operator, moves it: `make cache-declare ref=<commit>` resolves the ref to a full commit, extracts that commit's committed state with `git archive` below `INFINITO_CACHE_PIN_ROOT/<sha>` (`$XDG_DATA_HOME/infinito/cache`), outside every checkout, prunes the checkouts of all earlier commits but the previous pin, and applies it; while the frontend is not running it only pins, and the next `make cache-apply` applies the pin. `INFINITO_CACHE_PIN_ROOT` must be an absolute path outside the checkout, and an agent sandbox must allow writes below it and below the directory of `INFINITO_CACHE_PIN_FILE`. Materializing and applying hold a lock on `INFINITO_CACHE_PIN_ROOT/.lock`, and the apply reads the pin once the lock is held. `make cache-apply`, which `make compose-up` runs for every checkout, applies the same pinned checkout: it creates the Nexus proxy repositories, issues the frontend's leaf certificates, installs the pinned upstream map read-only onto the path the frontend mounts and reloads it. No checkout's working tree reaches the stack. A checkout's `compose.cache-consumer.yml` hijacks and apt sources name only the hosts the pinned commit declares identically; any other host keeps its real address, and while the configured pin cannot be read no host is hijacked there. Inner Dockerfile builds are not filtered yet: their `build.extra_hosts` still hijack every host in the checkout's own `INFINITO_CACHE_HOSTS` and `INFINITO_CACHE_HTTP_HOSTS`. `make cache-apply` refuses a frontend whose map lies outside `INFINITO_CACHE_PIN_ROOT`, as one an act container sees through the host daemon does; recreate it with `make infra-update`. A checkout whose own declarations differ from the pin gets a line per differing repository or host and `ask the declarer to bump the pin`; its deploy continues. Without a pin, `make cache-apply` fails naming `make cache-declare`, and `make compose-up` warns and keeps the map already served. Recreate the checkout's deploy stack with `make compose-up` after a bump so the new DNS hijacks reach it. `make cache-apply` exits with `INFINITO_CACHE_PIN_FILE is not set; run make dotenv` until `make dotenv` has written `INFINITO_CACHE_PIN_FILE` and `INFINITO_CACHE_PIN_ROOT`; [load.sh](../../../scripts/meta/env/load.sh) lets an exported value win over `.env`, so a shell that exports an `INFINITO_CACHE_PACKAGE_FRONTEND_CONF` outside the pin root makes every apply from it refuse the frontend.

A machine that still runs the legacy per-checkout cache stack moves to the pin once:

1. Every checkout on the pin code runs `make dotenv-force` once from a fresh shell. It writes `INFINITO_CACHE_PIN_FILE` and `INFINITO_CACHE_PIN_ROOT` and moves `INFINITO_CACHE_PACKAGE_FRONTEND_CONF` below the pin root.
2. The declarer runs `make cache-declare ref=<merge commit>` once. The legacy frontend still mounts the primary checkout's `compose/package-cache-frontend/upstreams.conf`, outside the pin root, so the pin is written and the apply refuses, naming that mount.
3. `make infra-up takeover=true` stops the legacy containers and starts the infra runner, which mounts the pin root. From then on the primary checkout's `compose/package-cache-frontend/upstreams.conf` is unused and may be deleted.
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

A repository is proxied by Nexus. A host is additionally answered for by the frontend, so a client keeps addressing its real upstream URL. `ports: ["80"]` serves it over plain HTTP and issues no certificate; `paths:` maps several repositories under one host; `mirror:` on a repository names the sibling the frontend retries against on `502`, `503` or `504`; `passthrough: true` suits an upstream that hands out URLs already carrying the repository prefix; `hijack: "false"` (quoted: the bootstrap reader takes strings only) suits a host far too broad to hijack, such as `github.com`: it gets no listener, no certificate and no `extra_hosts` entry, only the artefact base route `<base>/<host>/<path>` to its repository. Nexus follows the upstream's redirect to a file, such as a release asset's hop to GitHub's asset host, so the redirect target needs no declaration.

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
- The `artefacts:` section and every entry in it are mappings, and an entry carries only the keys `url`, `revision`, `sha256` and `bytes`, plus `unpacked_bytes` on an `argos-net.com` package; any other shape or key is a contract breach, not an empty declaration.
- An `argos-net.com` package must declare `unpacked_bytes`, the sum of the file sizes its archive lists, as a positive decimal integer. The store unpacks it once into `argos-packages/<sha256>` and refuses an archive that lists any other sum; `min_storage` counts the sum next to `bytes`.
- `url` is the absolute `https` URL of exactly one upstream file at the pinned revision. Its path holds only `A-Z a-z 0-9 . _ ~ / -` and no empty or all-dot segment (`.`, `..`). It carries no `%` anywhere, no query, no fragment, no userinfo, no port and no whitespace, because it ends up in shell lines and Dockerfiles.
- `url` resolves to exactly one repository: the one whose `upstream` is its longest prefix ending at a segment, so the prefetch knows which Nexus repository holds it; two repositories with that same upstream refuse it. An `https` url reaches its host's TLS listener, which routes every path to that host's repository: its `repo`, else the repository of its first `paths:` route, because `paths:` routes serve the plain-HTTP listeners only. So the url's host is declared under `cache: hosts:` with `443` among its `ports` (the default) or with `hijack: "false"`, its repository is this repository, and that repository's upstream is the host's root, so `<base>/<host>/<path>` reaches the same file through the same repository.
- `revision` is the immutable revision of the url, and its shape is set per host. On `huggingface.co` and `raw.githubusercontent.com` it is a 40-digit lowercase hex commit, because branches and tags move, and sits in the segment where the host keeps the ref. On `huggingface.co` that is the segment after `resolve` in `<org>/<repo>/resolve/<commit>/<file>`, optionally under `datasets/` or `spaces/`, with org, repo and file present and `resolve` once. On `raw.githubusercontent.com` it is the third segment of `<owner>/<repo>/<commit>/<file>`. On `argos-net.com`, which publishes no commits, it is the package version `<major>_<minor>[_<patch>]` that ends the file name `<name>-<version>.argosmodel`; a file name without that version is refused. On `github.com` only a release asset `<owner>/<repo>/releases/download/<tag>/<file>` is accepted, its revision is the tag, and the digest and size come from the release API; any other `github.com` path is refused. On every host `sha256` and `bytes` stay mandatory, so a file replaced under the same name fails closed. A host with no known layout is refused.
- `sha256` is the 64-digit lowercase hex digest of the file's bytes, and `bytes` its exact size as a positive decimal integer without a leading zero. One digest declared with two sizes is refused; two names may carry one digest, and the store then holds that file once.

A consumer fetches `<base>/<host>/<path>`, where `<host>` is the url's host and `<path>` its path without the leading slash. The base is an `http` or `https` URL of a host with an optional port from 1 to 65535 and an optional path prefix, without a trailing slash, whitespace, `%`, userinfo, query or fragment; the value `https:/` makes the expression the url itself, an empty base makes `url_for` and `records` keep the upstream, and both refuse any other shape. Core reads the base bare, as `${INFINITO_ARTEFACT_BASE}`: [default.env](../../../default.env) declares the key with the value `https:/`, and `make dotenv` replaces it with `http://<INFINITO_CACHE_PACKAGE_FRONTEND_IP>` while `INFINITO_CACHE_STACK` is true ([artefact_base.py](../../../utils/env/handlers/infinito/cache/artefact_base.py)); an exported value or a line in `custom.env` wins. The frontend answers `/<host>/<path>` on its port 80 `default_server` for every host with a TLS listener and proxies it to the repository that listener serves. A consumer outside core reads no `default.env` and writes `${INFINITO_ARTEFACT_BASE:-https:/}`.

A consumer verifies the sha256 of what it fetched and fails on a mismatch; it never accepts a different file. A matching digest pins the size too, so in a Dockerfile `ADD --checksum=sha256:<sha256>`, which checks the digest only, is enough; `bytes` feeds the store's size accounting. A consumer may retry the upstream when the base does not answer or answers 5xx.

## Background 📚

- Compose-file env-var contract: [compose.yml.md](../artefact/files/compose.yml.md)
- Profile gating mechanics: [profile.py](../../../cli/administration/deploy/development/profile.py)
- Infra runner compose call: [stack.py](../../../cli/administration/deploy/development/stack.py)
