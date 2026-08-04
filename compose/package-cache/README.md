# Package-Cache Wiring 📦

Client-side configuration bind-mounted into the `infinito` runner so that pip, npm, and apt route through the Sonatype Nexus 3 OSS pull-through proxy.

For services, activation, coverage, and operations of the local cache stack, see [cache.md](../../docs/contributing/environment/cache.md).

## Files 📄

- `pip.conf`: pip configuration. Mounted at `/etc/pip.conf`. Routes pip through `pypi-proxy`.
- `npmrc`: npm configuration. Mounted at `/root/.npmrc`. Routes npm through `npm-proxy`.
- `apt/<distro>.list`: apt sources, one file per `INFINITO_DISTRO`. The matching file is mounted at `/etc/apt/sources.list.d/package-cache.list`. `apt/debian.list` routes apt through `apt-debian`, `apt/ubuntu.list` through `apt-ubuntu`; the pacman/dnf distros get an empty file, because `apt-get update` fails as a whole on a single unreachable source and must not carry a foreign distro's entry.
