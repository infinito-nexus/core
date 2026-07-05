# Tor Onion Service

## Description

Runs a [Tor](https://www.torproject.org/) daemon on the node and publishes a Tor v3 onion service, turning an Infinito.Nexus instance behind NAT/CGNAT into a fully Tor-reachable node without a public IP, port forwarding, VPS, or DynDNS.

## Overview

When `svc-net-tor` is deployed, the node's `DOMAIN_PRIMARY` is the minted `.onion` address, so the whole stack (web vhosts, Keycloak SSO, LDAP, CA) resolves onion domains consistently. The Tor daemon runs as a host-network compose sidecar and maps one hidden service to the host OpenResty (`HiddenServicePort 80 -> 127.0.0.1:80`); per-app subdomains (`<app>.<node>.onion`) are routed by the `Host` header. TLS is off on the onion side (onion v3 already provides transport encryption + server authentication); apps still receive `X-Forwarded-Proto: https` because `.onion` is a browser Secure Context.

The onion key is minted offline during inventory build (`cli.administration.inventory.onion`) and stored in the inventory, so the address is stable across redeploys and restorable from a backup.

## Features

- **Full onion node:** `DOMAIN_PRIMARY` becomes the node `.onion`; the entire stack shifts to Tor with no domain-transform logic.
- **Single key, per-app subdomains:** one hidden service serves every app at `<app>.<node>.onion`, Host-routed by OpenResty.
- **Offline deterministic minting:** the v3 key/address is generated without running Tor and pinned in the inventory (stable, backupable, restorable).
- **HTTP on the onion side:** TLS is forced off for `.onion` (no Let's Encrypt possible); onion v3 crypto is the transport auth.
- **Optional public domains:** extra clearnet domains added to an app keep their own TLS flavor and deploy alongside the onion.
- **Configurable egress:** inbound is always onion; outbound torification is off by default (`TOR_EGRESS_ENABLED`).

## Limitations

- Targets **fresh** onion nodes; converting an existing clearnet node is out of scope (the LDAP base DN and all identities would shift).
- **No Let's Encrypt** for `.onion` (ACME requires public DNS).
- Outbound mail from `@<node>.onion` senders is not deliverable to the public Internet; onion does not replace public Internet email.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
