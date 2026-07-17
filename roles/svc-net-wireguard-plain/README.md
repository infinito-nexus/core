# Wireguard Client

## Description

This role manages WireGuard on a client system. It sets up essential services and scripts to configure and optimize WireGuard connectivity.

## Overview

Optimized for client configurations, this role:

- Deploys a systemd service and its associated script to set the MTU on specified network interfaces.
- Uses a Jinja2 template to generate the `set-mtu.sh` script.
- Ensures that the MTU is configured correctly before starting WireGuard with [wg-quick](https://www.wireguard.com/quickstart/).

## Cosmos

The diagram places Wireguard Client in the Infinito.Nexus cosmos: the components it deploys (capabilities), the central services it consumes (dependencies), and its outward reach (federation and bridged external networks).

```mermaid
flowchart LR
    subgraph role [svc-net-wireguard-plain 💻]
        svc_wireguard_plain["wireguard-plain"]
    end
```

Solid `1:1` edges are fixed relationships; dashed `0..1` edges are conditional (enabled only in matching deployments). Node markers show the role's deploy modes (💻 host, 🐳 compose, 🐝 swarm); ❌ marks a service that is explicitly turned off.

## Purpose

The primary purpose of this role is to configure WireGuard on a client by setting appropriate MTU values on network interfaces. This ensures a stable and optimized VPN connection.

## Features

- **MTU Configuration:** Deploys a template-based script to set the MTU on all defined internet interfaces.
- **Systemd Service Integration:** Creates and manages a systemd service to execute the MTU configuration script.
- **Administration Support:** For client key creation and further setup, please refer to the [Administration](./Administration.md) file.
- **Modular Design:** Easily integrates with other WireGuard roles or network configuration roles.

## Quick Setup

### Development

Clone, set up the workstation, and deploy Wireguard Client onto the local stack:

```bash
git clone https://github.com/infinito-nexus/core.git
cd core
make onboard
make compose-deploy mode=reinstall apps=svc-net-wireguard-plain full_cycle=false
```

### Production

Run the published image to provision the inventory and deploy Wireguard Client to a managed server (the mounted volume persists the inventory between the two runs):

```bash
docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  ghcr.io/infinito-nexus/core/debian \
  infinito administration inventory provision /etc/infinito.nexus/inventories/prod \
  --inventory-file /etc/infinito.nexus/inventories/prod/devices.yml \
  --host <your-server> \
  --vars-file inventories/<env>/default.yml \
  --include 'svc-net-wireguard-plain'

docker run --rm -it \
  -v "$PWD/inventories:/etc/infinito.nexus/inventories" \
  ghcr.io/infinito-nexus/core/debian \
  infinito administration deploy dedicated /etc/infinito.nexus/inventories/prod/devices.yml \
  --password-file /etc/infinito.nexus/inventories/prod/.password \
  --id svc-net-wireguard-plain \
  --diff \
  -vv
```

## Further Resources

- [WireGuard Documentation](https://www.wireguard.com/)
- [ArchWiki: WireGuard](https://wiki.archlinux.org/index.php/WireGuard)
- [Subnetting Basics](https://www.scaleuptech.com/de/blog/was-ist-und-wie-funktioniert-subnetting/)
- [WireGuard Permissions Issue Discussion](https://bodhilinux.boards.net/thread/450/wireguard-rtnetlink-answers-permission-denied)
- [UFW and SSH via WireGuard](https://unix.stackexchange.com/questions/717172/why-is-ufw-blocking-acces-to-ssh-via-wireguard)
- [OpenWrt Forum Discussion on WireGuard](https://forum.openwrt.org/t/cannot-ssh-to-clients-on-lan-when-accessing-router-via-wireguard-client/132709/3)
- [WireGuard Connection Dies on Ubuntu](https://serverfault.com/questions/1086297/wireguard-connection-dies-on-ubuntu-peer)
- [SSH Fails with WireGuard IP](https://unix.stackexchange.com/questions/624987/ssh-fails-to-start-when-listenaddress-is-set-to-wireguard-vpn-ip)
- [WireGuard NAT and Firewall Issues](https://serverfault.com/questions/210408/cannot-ssh-debug1-expecting-ssh2-msg-kex-dh-gex-reply)

## Credits

Implemented by **[Kevin Veen-Birkenbach](https://www.veen.world)**.
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code) and maintained by [Kevin Veen-Birkenbach](https://www.veen.world).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
