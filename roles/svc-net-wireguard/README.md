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
joins an upstream peer), selected by `services.wireguard.mode`. It assembles a Compose stack from the
shared `sys-svc-compose` / `sys-svc-container` bases, grants the container the capabilities WireGuard
needs, optionally masquerades client traffic, and publishes the tunnel port. It is the containerized
successor to the host-native `svc-net-wireguard-core`, `svc-net-wireguard-plain`, and
`svc-net-wireguard-firewalled` roles. For client/peer key management see [Administration.md](./Administration.md).

## Features

- **Server and client modes:** One `services.wireguard.mode` switch picks peer termination (`PEERS`
  set) or joining an upstream peer; replaces the old `-core` / `-plain` split.
- **NAT masquerading:** `services.wireguard.nat` preserves the legacy firewalled behaviour
  (`iptables` FORWARD + POSTROUTING MASQUERADE) for clients behind NAT.
- **Host/container ownership mapping:** `PUID` / `PGID` map `/config` ownership onto a host user per
  the linuxserver [User/Group Identifiers](https://docs.linuxserver.io/images/docker-wireguard/#user-group-identifiers) contract.
- **Pinned image:** The upstream tag is pinned in `meta/services.yml`; bump and redeploy to upgrade.
- **Docker-in-Docker test harness:** The `tests/` suite stands up at least three servers and asserts
  peer handshakes, then builds a full mesh across all six nodes (3 servers + CentOS/Debian/Manjaro
  clients) and verifies every node reaches every other (handshake + ICMP ping).

## Migration

| Legacy role | Behaviour | Replacement |
|-------------|-----------|-------------|
| `svc-net-wireguard-core` | host package + `wg-quick` server, sysctl IP-forward, `/etc/wireguard/wg0.conf` | `mode: server` (linuxserver image, `PEERS` set) |
| `svc-net-wireguard-plain` | systemd unit forcing MTU 1400 on the uplink | `mode: client` + `services.wireguard.client.mtu` |
| `svc-net-wireguard-firewalled` | `iptables` FORWARD + NAT MASQUERADE behind NAT | `mode: client` + `services.wireguard.nat: true` (same rules) |

## Developer notes

See [Administration.md](./Administration.md) for peer key creation, config activation, and live
container inspection. The end-to-end harness lives under `tests/`: `e2e.sh` orchestrates `local.sh` (servers),
`external.sh` (server handshakes) and `mesh.sh` (full mesh across all 6 nodes: 3 servers +
CentOS/Debian/Manjaro clients, all-pairs handshake + ping). `WIREGUARD_E2E_BACKEND` selects the
provisioning backend (Compose today).

The harness is discovered and run automatically by the `test-e2e-cli` role (the CLI counterpart to
`test-e2e-playwright`): any role shipping `tests/e2e.sh` is picked up post-deploy and run in the deploy
container (Docker-in-Docker via the host socket), with `tests/test.env.j2` rendered as its env.

## Further resources

- [WireGuard official website](https://www.wireguard.com/)
- [linuxserver/wireguard image](https://docs.linuxserver.io/images/docker-wireguard/)
- [ArchWiki: WireGuard](https://wiki.archlinux.org/index.php/WireGuard)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
