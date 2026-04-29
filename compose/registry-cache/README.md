# Registry-Cache Wiring 🪞

Static configuration that wires the `infinito` runner container to the
`registry-cache` pull-through proxy defined in
[compose.yml](../../compose.yml). The proxy
(`rpardini/docker-registry-proxy`) intercepts every outbound docker
registry pull from `infinito`'s inner dockerd and caches blobs and
manifests so re-deploys and local fresh-purges do not trigger live
registry round-trips.

## Activation 🎚️

The proxy lives in its own compose profile (`cache`) and is selected
by [profile.py](../../cli/deploy/development/profile.py):

- Active on developer machines, where the host disk persists between
  deploys and cross-run dedup pays off.
- Inactive in CI runs (`GITHUB_ACTIONS=true`, `RUNNING_ON_GITHUB=true`,
  or `CI=true`); fresh runner disks would not benefit from cross-run
  dedup and the proxy startup is net loss.

When inactive, `infinito.depends_on.registry-cache` is `required: false`
so Compose does not pull the proxy in via the dependency, and the
systemd drop-in bind-mount falls back to `/dev/null` so dockerd boots
without `HTTP_PROXY`.

## Scope 📋

- This directory MUST contain only files consumed by the
  `registry-cache` compose service or its peer `infinito` container.
- The systemd drop-in `proxy.conf` is bind-mounted to
  `/etc/systemd/system/docker.service.d/registry-cache-proxy.conf` via
  [compose.yml](../../compose.yml) when the `cache` profile is active.
  Changes take effect on the next container start without an image
  rebuild.
- The companion CA-install script lives at
  [registry-ca.sh](../../scripts/docker/cache/registry-ca.sh)
  because it is called by dockerd's `ExecStartPre`, which expects the
  binary on the runner's `$PATH`. It is bind-mounted to
  `/usr/local/bin/registry-cache-ca.sh`; the file MUST keep its
  git +x bit because bind-mounts preserve host permissions.

## Files 📄

- `proxy.conf`: systemd drop-in for `docker.service`. Sets
  `HTTP_PROXY` / `HTTPS_PROXY` to the proxy and registers the CA-install
  script as `ExecStartPre`.

For the env-variable contract that governs cache size and host paths,
see the Registry Cache section in
[compose.yml.md](../../docs/contributing/artefact/files/compose.yml.md).
