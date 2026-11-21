# Registry-Cache Wiring 🪞

Static configuration consumed by the `registry-cache` compose service and bind-mounted into the `infinito` runner.

For services, activation, coverage, and operations of the local cache stack, see [cache.md](../../docs/contributing/environment/cache.md).

## Files 📄

- `proxy.conf`: systemd drop-in for `docker.service`. Sets `HTTP_PROXY`/`HTTPS_PROXY` to the proxy and registers [registry-ca.sh](../../scripts/docker/cache/registry-ca.sh) as `ExecStartPre`.
- `entrypoint.sh`: entrypoint of the `registry-cache` service. Runs the image's own entrypoint with `inactive=<INFINITO_CACHE_MAX_IDLE_DAYS>d` in its `proxy_cache_path` line, beside `max_size=<INFINITO_CACHE_REGISTRY_MAX_SIZE>`, and fails before nginx starts when the pinned image no longer writes the line it replaces.
