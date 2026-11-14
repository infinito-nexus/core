# Package-Cache Wiring 📦

Client-side configuration bind-mounted into the `infinito` runner so that pip and npm route through the Sonatype Nexus 3 OSS pull-through proxy.

For services, activation, coverage, and operations of the local cache stack, see [cache.md](../../docs/contributing/environment/cache.md).

## Files 📄

- `pip.conf`: pip configuration. Mounted at `/etc/pip.conf`. Routes pip through `pypi-proxy`.
- `npmrc`: npm configuration. Mounted at `/root/.npmrc`. Routes npm through `npm-proxy`.
