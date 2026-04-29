# Package-Cache Wiring 📦

Static configuration that wires the `infinito` runner container to the
`package-cache` pull-through proxy defined in
[compose.yml](../../compose.yml). The proxy
([sonatype/nexus3](https://hub.docker.com/r/sonatype/nexus3)) caches
package-manager downloads (pypi, npm, apt, helm, raw) so re-deploys and
local fresh-purges do not trigger live upstream traffic. Companion to
the existing [registry-cache](../registry-cache/README.md), which
covers Docker image pulls.

## Activation 🎚️

The proxy lives in the shared `cache` compose profile and is selected
by [profile.py](../../cli/deploy/development/profile.py):

- Active on developer machines, where the host disk persists between
  deploys and cross-run dedup pays off.
- Inactive in CI runs (`GITHUB_ACTIONS=true`, `RUNNING_ON_GITHUB=true`,
  or `CI=true`); fresh runner disks would not benefit from cross-run
  dedup and the proxy startup is net loss.

When inactive, `infinito.depends_on.package-cache` is `required: false`
so Compose does not pull the proxy in via the dependency, and every
client-config bind-mount in this directory falls back to `/dev/null`
so the runner deploys identically with the cache off.

## Scope 📋

- This directory MUST contain only client-side configuration that
  routes a package manager inside `infinito` through the Nexus proxy.
- The bootstrap helper that creates Nexus's blobstore and proxy repos
  lives at
  [package.sh](../../scripts/docker/cache/package.sh)
  and is invoked from
  [up.py](../../cli/deploy/development/up.py) once after the stack is
  healthy under the `cache` profile.
- Each client-config file is bind-mounted to a fixed path inside the
  runner via `compose.yml`. The bind source is gated through a
  per-file `${INFINITO_PACKAGE_CACHE_*_CONF:-/dev/null}` env var that
  the [Profile](../../cli/deploy/development/profile.py) class sets
  only when the `cache` profile is active.

## Files 📄

- `pip.conf`: pip configuration. Mounted at `/etc/pip.conf` inside the
  runner. Routes pip through `pypi-proxy`.
- `npmrc`: npm configuration. Mounted at `/root/.npmrc`. Routes npm
  through `npm-proxy`.
- `apt.list`: apt sources list. Mounted at
  `/etc/apt/sources.list.d/package-cache.list`. Routes apt through
  `apt-debian` (Debian runners) and `apt-ubuntu` (Ubuntu runners).

The bootstrap helper also registers a `helm-bitnami` proxy repo for
future helm-driven roles. No client snippet ships today because no
role pulls helm charts; the proxy registration is zero-cost prep.

For the env-variable contract that governs admin password, heap sizing,
blobstore quota, and host paths, see the Package Cache section in
[compose.yml.md](../../docs/contributing/artefact/files/compose.yml.md).
