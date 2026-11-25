# Registry-Cache Wiring 🪞

Static configuration consumed by the `registry-cache` compose service and bind-mounted into the `infinito` runner.

For services, activation, coverage, and operations of the local cache stack, see [cache.md](../../docs/contributing/environment/cache.md).

## Files 📄

- `proxy.conf`: systemd drop-in for `docker.service`. Sets `HTTP_PROXY`/`HTTPS_PROXY` to the proxy and registers [registry-ca.sh](../../scripts/docker/cache/registry-ca.sh) as `ExecStartPre`.
- [entrypoint.sh](../../roles/svc-registry-cache/files/shell/entrypoint.sh): entrypoint of the multi-proxy `cache` service of `svc-registry-cache`. Runs the image's own entrypoint with `CACHE_INACTIVE=<INFINITO_CACHE_MAX_IDLE_DAYS>d` beside `CACHE_MAX_SIZE=<INFINITO_CACHE_REGISTRY_MAX_SIZE>`, and fails before nginx starts when the pinned image no longer reads `CACHE_INACTIVE` in its `proxy_cache_path` line.
