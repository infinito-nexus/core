# Package-Cache Frontend (TLS-terminating reverse proxy) 🔐

TLS-terminating reverse proxy in front of the Sonatype Nexus 3 OSS [`package-cache`](../package-cache/README.md) service. Owns the real upstream package-manager hostnames via DNS-hijack so clients reach the cache transparently.

For services, activation, coverage, and operations of the local cache stack, see [cache.md](../../docs/contributing/environment/cache.md).

## Files 📄

- `upstreams.conf`: nginx server-blocks, generated from the `cache:` declarations by [render.py](../../utils/cache/render.py) and therefore untracked. HTTPS (port 443) per hostname for runner-side traffic, HTTP (port 80) for inner-`dockerd` Dockerfile builds. Bind-mounted at `/etc/nginx/conf.d/upstreams.conf`.
