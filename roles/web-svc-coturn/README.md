# Coturn

This folder contains the role to deploy and manage a [Coturn](https://github.com/coturn/coturn) service.

## Description

[Coturn](https://github.com/coturn/coturn) is a free and open-source **TURN (Traversal Using Relays around NAT)** and **STUN (Session Traversal Utilities for NAT)** server.  
It enables real-time communication (RTC) applications such as **WebRTC** to work reliably across NATs and firewalls.

Without TURN/STUN, video calls, conferencing, and peer-to-peer connections often fail due to NAT traversal issues.  
Coturn solves this by acting as a **relay server** and/or **discovery service** for public IP addresses.

More background:  

- Wikipedia: [Traversal Using Relays around NAT](https://en.wikipedia.org/wiki/Traversal_Using_Relays_around_NAT)  
- Wikipedia: [Session Traversal Utilities for NAT](https://en.wikipedia.org/wiki/STUN)  
- Official Coturn Docs: [https://github.com/coturn/coturn/wiki](https://github.com/coturn/coturn/wiki)

## Overview

This role deploys Coturn via Docker Compose using the `sys-stk-semi-stateless` stack.  
It automatically configures:

- TURN and STUN listening ports
- Relay port ranges
- TLS certificates (via Let’s Encrypt integration)
- Long-term credentials and/or REST API secrets

Typical use cases:

- Nextcloud Talk
- Jitsi
- BigBlueButton
- Any WebRTC-based application

## Features

- Stateless container deployment (no database or persistent volume required)  
- Automatic TLS handling via `sys-stk-front-base`  
- TURN and STUN support over TCP and UDP  
- Configurable relay port ranges for scaling  
- Configurable server-wide allocation quota (`services.coturn.total_quota`, default 2000); size it at about 2·N² for every concurrent Nextcloud Talk call with N participants, as each participant opens N peer connections and requests one allocation per TURN transport
- Pinned addresses on host networking in compose mode when the host carries `networks.internet.ip4` on an interface and carries `networks.internet.ip6` too or leaves it unset: listens on `networks.internet.ip4`, `127.0.0.1` for the healthcheck and the set `networks.internet.ip6`, and places every relay on `networks.internet.ip4` instead of on the Docker bridge addresses of the host. Any other host, such as one behind 1:1 NAT, keeps listening and relaying on every local address
- Integration into Infinito.Nexus inventory/variable system

## Further Resources

- Coturn Project: [github.com/coturn/coturn](https://github.com/coturn/coturn)  
- Coturn Wiki: [github.com/coturn/coturn/wiki](https://github.com/coturn/coturn/wiki)  
- TURN on Wikipedia: [en.wikipedia.org/wiki/Traversal_Using_Relays_around_NAT](https://en.wikipedia.org/wiki/Traversal_Using_Relays_around_NAT)  
- STUN on Wikipedia: [en.wikipedia.org/wiki/STUN](https://en.wikipedia.org/wiki/STUN)
