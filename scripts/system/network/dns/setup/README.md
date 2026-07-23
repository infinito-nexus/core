# DNS Setup Scripts 🌐

This directory contains platform-specific scripts for setting up local DNS resolution for the `infinito.test` domain (and subdomains) on the development machine.

All scripts map `*.infinito.test` → `127.0.0.1` so that local deployments are reachable via their expected hostnames.

---

## Scripts 📄

### `linux.sh` 🐧

General-purpose DNS setup for Linux systems. Supports multiple strategies depending on the environment:

- **NetworkManager + dnsmasq**. preferred path when NetworkManager is active; configures the NM dnsmasq plugin with a wildcard zone entry.
- **System dnsmasq**. fallback when NetworkManager is not running; configures a standalone dnsmasq service.
- **`/etc/hosts` fallback**. used in non-systemd environments (e.g. Docker containers, LXC) where service management is unavailable; writes a managed block of host entries directly into the hosts file.

Shared helper functions are sourced from [`../common.sh`](../common.sh).

### `wsl.sh` 🪟

WSL2-specific DNS setup. Only executes when running inside a WSL2 environment (detected via `/proc/version`). Configures:

- **dnsmasq** with the discovered WSL2 upstream DNS gateway as forwarder.
- **systemd-resolved** stub listener disabled to avoid port conflicts.
- **`/etc/resolv.conf`** pointed at the local dnsmasq instance (`127.0.0.1`).
- **`/etc/wsl.conf`** set to `generateResolvConf=false` to prevent WSL from overwriting the resolver config on restart.

---

## Related 🔗

- [Makefile Commands](../../../../../docs/contributing/tools/make.md). canonical Make target index for this area
- [`../remove.sh`](../remove.sh). teardown script that undoes the DNS configuration
- [`../common.sh`](../common.sh). shared variables and helper functions used by `linux.sh`
