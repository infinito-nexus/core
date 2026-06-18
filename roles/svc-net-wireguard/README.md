# WireGuard

## Description

[WireGuard](https://www.wireguard.com/) is a fast, modern, secure VPN tunnel that uses
state-of-the-art cryptography. It runs as a small, auditable codebase and presents itself as an
ordinary network interface, making encrypted point-to-point and roaming-client connectivity simple to
operate.

## Overview

This role runs WireGuard in a Docker container using the
[linuxserver/wireguard](https://docs.linuxserver.io/images/docker-wireguard/) image, in either
**server** mode (this host terminates peers and generates their configs) or **client** mode (this host
joins an upstream peer), selected by the `services.wireguard.flavor` list (`server`, `client`, `nat`). It assembles a Compose stack from the
shared `sys-svc-compose` / `sys-svc-container` bases, grants the container the capabilities WireGuard
needs, optionally masquerades client traffic, and publishes the tunnel port. It is the containerized
successor to the host-native `svc-net-wireguard-core`, `svc-net-wireguard-plain`, and
`svc-net-wireguard-firewalled` roles. For client/peer key management see [Administration.md](./Administration.md).

## Features

- **Server and client flavors:** The `services.wireguard.flavor` list picks peer termination (`PEERS`
  set) or joining an upstream peer; replaces the old `-core` / `-plain` split.
- **NAT masquerading:** the `nat` flavor preserves the legacy firewalled behaviour
  (`iptables` FORWARD + POSTROUTING MASQUERADE) for clients behind NAT.
- **Host/container ownership mapping:** `PUID` / `PGID` map `/config` ownership onto a host user per
  the linuxserver [User/Group Identifiers](https://docs.linuxserver.io/images/docker-wireguard/#user-group-identifiers) contract.
- **Pinned image:** The upstream tag is pinned in `meta/services.yml`; bump and redeploy to upgrade.
- **Deploy-driven test harness:** The `files/test/` suite boots 6 empty containers (3 `debian:latest`
  servers + Manjaro/Debian/CentOS workstations), runs `make install` in each, provisions a dedicated
  inventory per host with a full-mesh `wg0.conf`, deploys this role into each (Docker-in-Docker), and
  asserts every node reaches every other over WireGuard.

## Migration

| Legacy role | Behaviour | Replacement |
|-------------|-----------|-------------|
| `svc-net-wireguard-core` | host package + `wg-quick` server, sysctl IP-forward, `/etc/wireguard/wg0.conf` | `flavor: [server]` (linuxserver image, `PEERS` set) |
| `svc-net-wireguard-plain` | systemd unit forcing MTU 1400 on the uplink | `flavor: [client]` + `services.wireguard.client.mtu` |
| `svc-net-wireguard-firewalled` | `iptables` FORWARD + NAT MASQUERADE behind NAT | `flavor: [client, nat]` (same rules) |

## Developer notes

See [Administration.md](./Administration.md) for peer key creation, config activation, and live
container inspection. The end-to-end harness lives under `files/test/`: `test.sh` orchestrates
`01_bootstrap.sh` (boot 6 empty containers + `make install`), `02_registration.sh` (per-host dedicated
inventory + full-mesh `wg0.conf`), and `03_handshake.sh` (deploy this role per host + all-pairs check).

The harness is discovered and run automatically by the `test-e2e-cli` role: any role shipping
`templates/test.env.j2` plus `files/test/test.sh` is picked up post-deploy and run in the deploy
container (Docker-in-Docker via the host socket), with `templates/test.env.j2` rendered as its env.

## Further resources

- [WireGuard official website](https://www.wireguard.com/)
- [linuxserver/wireguard image](https://docs.linuxserver.io/images/docker-wireguard/)
- [ArchWiki: WireGuard](https://wiki.archlinux.org/index.php/WireGuard)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
