# Wireguard Client

## Description

This role manages WireGuard on a client system. It sets up essential services and scripts to configure and optimize WireGuard connectivity.

## Overview

Optimized for client configurations, this role:

- Deploys a systemd service and its associated script to set the MTU on specified network interfaces.
- Uses a Jinja2 template to generate the `set-mtu.sh` script.
- Ensures that the MTU is configured correctly before starting WireGuard with [wg-quick](https://www.wireguard.com/quickstart/).

## Purpose

The primary purpose of this role is to configure WireGuard on a client by setting appropriate MTU values on network interfaces. This ensures a stable and optimized VPN connection.

## Features

- **MTU Configuration:** Deploys a template-based script to set the MTU on all defined internet interfaces.
- **Systemd Service Integration:** Creates and manages a systemd service to execute the MTU configuration script.
- **Administration Support:** For client key creation and further setup, please refer to the [Administration](./Administration.md) file.
- **Modular Design:** Easily integrates with other WireGuard roles or network configuration roles.

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

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
