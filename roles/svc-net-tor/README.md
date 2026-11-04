# Tor Onion Service

## Description

Runs a [Tor](https://www.torproject.org/) daemon on the node and publishes a Tor v3 onion service, turning an Infinito.Nexus instance behind NAT/CGNAT into a fully Tor-reachable node without a public IP, port forwarding, VPS, or DynDNS.

## Overview

When `svc-net-tor` is deployed, the node runs in the `multi` network mode by default: every role with a Tor bond keeps its clearnet domains and gains one `<sub>.<node>.onion` sibling per domain, each served by its own vhost. `NETWORK_MODE: tor` serves those roles on onion only (see [network_modes.md](../../docs/contributing/design/network_modes.md)). The Tor daemon runs as a host-network compose sidecar and maps one hidden service to the host OpenResty (`HiddenServicePort 80 -> 127.0.0.1:80`); per-app subdomains (`<app>.<node>.onion`) are routed by the `Host` header. Onion vhosts serve plain HTTP (onion v3 already provides transport encryption and server authentication), so apps behind them receive `X-Forwarded-Proto: http`.

The onion key is minted offline during inventory build (`cli.administration.inventory.onion`) and stored in the inventory, so the address is stable across redeploys and restorable from a backup.

## Features

- **Full onion node:** `DOMAIN_PRIMARY` becomes the node `.onion`; the entire stack shifts to Tor with no domain-transform logic.
- **Single key, per-app subdomains:** one hidden service serves every app at `<app>.<node>.onion`, Host-routed by OpenResty.
- **Offline deterministic minting:** the v3 key/address is generated without running Tor and pinned in the inventory (stable, backupable, restorable).
- **HTTP on the onion side:** TLS is forced off for `.onion` (no Let's Encrypt possible); onion v3 crypto is the transport auth.
- **Optional public domains:** extra clearnet domains added to an app keep their own TLS flavor and deploy alongside the onion.
- **Configurable egress:** inbound is always onion; outbound torification is on by default (`TOR_EGRESS_ROUTER_ENABLED`).

## Limitations

- Targets **fresh** onion nodes; converting an existing clearnet node is out of scope (the LDAP base DN and all identities would shift).
- **No Let's Encrypt** for `.onion` (ACME requires public DNS).
- Outbound mail from `@<node>.onion` senders is not deliverable to the public Internet; onion does not replace public Internet email.
