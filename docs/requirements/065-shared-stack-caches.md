# 065 - Shared stack caches and release after rescue

## User Story

As an operator who runs several compose slots, swarm lab clusters and GUI lanes on one host, I want repeated package and tool downloads to land in one shared host cache folder and every swarm or roundtrip run to release its cluster once the rescue bundle is saved, so that parallel stacks stop filling the root filesystem.

## Acceptance Criteria

- [ ] `make dotenv` writes `INFINITO_CACHE_SHARED_HOST_PATH=<DIR_CACHE>/shared` unless the environment or `custom.env` sets another path.
- [ ] With the cache stack enabled and `INFINITO_CACHE_SHARED_HOST_PATH` set, `docker compose config` of a compose slot shows that folder bind-mounted read-write at the same path into the `infinito` service, with `PIP_CACHE_DIR` and `npm_config_cache` pointing below it.
- [ ] With `INFINITO_CACHE_SHARED_HOST_PATH` set, rendering `compose/swarm/compose.yml` with `compose/swarm/cache.override.yml` and `compose/swarm/shared-cache.override.yml` shows the same read-write bind on the manager, both workers, the NFS server and the backup host.
- [ ] With `INFINITO_CACHE_SHARED_HOST_PATH` and `INFINITO_CACHE_HOST_PACMAN_PATH` empty or missing from `.env`, a compose slot renders and starts without the cache mounts and the cache environment, and `docker compose config` of its services is byte-identical to the render of the same `.env` before this change.
- [ ] `make dotenv` writes the host's pacman cache directory to `INFINITO_CACHE_HOST_PACMAN_PATH` only when the host's `/etc/os-release` `ID` is exactly `arch` and the stack runs arch; on Manjaro and every other host or stack the value is empty and pacman uses the shared folder alone.
- [ ] With `INFINITO_CACHE_HOST_PACMAN_PATH` and `INFINITO_CACHE_SHARED_HOST_PATH` set, the rendered compose slot and every rendered swarm lab node mount the host pacman cache read-only at the same path.
- [ ] `scripts/docker/cache/pacman.sh` rewrites `[options]` of a `pacman.conf` so that the read-only host cache is the first `CacheDir`, the node's own download directory `<shared>/pacman/node-XXXXXX/` the second and `<shared>/pacman/` the third, gives two nodes on one shared folder different download directories, removes every other `CacheDir` line, writes a `PostTransaction` hook that renames finished downloads from the node download directory into `<shared>/pacman/`, gives the same result when run twice, and leaves a system without `pacman.conf` untouched.
- [ ] `make compose-up` and the swarm node bootstrap run that script in every arch runner and arch lab node that mounts the shared folder.
- [ ] A package pacman downloads on an arch runner or lab node lands in `<shared>/pacman/` once its transaction completes, two nodes that download the same package at the same time never write the same file, and the host cache directory stays byte-identical.
- [ ] apt and dnf keep their per-container caches and reach the package cache proxies as before; `docs/contributing/environment/cache.md` states this next to the folder layout.
- [ ] `docs/contributing/environment/cache.md` documents the folder layout, both variables and the mount contract a GUI lane follows.
- [ ] Images keep reaching every inner daemon through `infinito-registry-cache`; no compose file shares a docker data root between daemons.
- [ ] `make swarm-zombie` without `keep=true` copies the act job's rescue diagnostics and Playwright artefacts to the same paths on the host and then removes the lab nodes, the lab network, the NFS export volume and the act outer container, on success and on failure.
- [ ] `make swarm-zombie keep=true` copies the same artefacts and leaves the cluster and the act outer container up.
- [ ] When the artefact copy fails, the lab nodes are still removed, the act outer container stays, and the run exits non-zero naming `make swarm-down`.
- [ ] `make roundtrip` hands `keep` to every swarm step, so a failed swarm step releases its cluster the same way a green one does.
- [ ] `make clean-cache` removes the shared cache folder.
- [ ] The disc-space cleanup cleans only pacman cache directories it can write, so a read-only host cache layer cannot fail it.
- [ ] `INFINITO_DISTRO` resolves exactly as before this change; deriving the default distro from the host ships as a separate follow-up.
- [ ] Every changed logic has one unit test, and each of these tests fails on the code before this change.
