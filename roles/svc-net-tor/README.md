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
- **Egress route:** `services.tor.egress.route` (`TOR_EGRESS_ROUTE`) decides where outbound traffic goes; inbound stays onion plus the clearnet siblings either way.
  - `none` leaves egress alone: no resolver, no packet filter, no TransPort. Both lists must be empty.
  - `onion` (default) resolves and routes `.onion` through Tor and leaves everything else direct.
  - `all` sends every outbound connection of the node and its containers through Tor and fails closed: TCP goes to the TransPort, every other protocol to an unlisted destination is dropped, and names outside the direct list resolve only through Tor's DNSPort. DNS reaches only loopback, the bridge and the deployed roles' own subnets, so no LAN resolver answers beside Tor; systemd-resolved, resolv.conf and the docker daemon lose their clearnet fallback. When Tor is down, that traffic fails; there is no clearnet fallback. Compose only.
- **Tor and direct lists:** `egress.tor` and `egress.direct` each carry an `include` and an `except`; entries are host names, `*.` wildcards, IPs and CIDRs. A host name covers its subdomains, so `example.org` and `*.example.org` mean the same. `except` only narrows its own `include`, a destination both lists keep takes Tor, and the route decides everything no list matches. `.onion` can never be direct.
- **Infrastructure pre-fill:** `direct.include` defaults to the package mirrors and time servers of the supported distributions, the registries (and their blob hosts) of every image the deployed applications pull, and the ACME endpoint, all declared under `egress.infrastructure`. These services see the node's own address; replace or empty the list in the inventory to change that.

## Limitations

- Targets **fresh** onion nodes; converting an existing clearnet node is out of scope (the LDAP base DN and all identities would shift).
- **No Let's Encrypt** for `.onion` (ACME requires public DNS).
- Outbound mail from `@<node>.onion` senders is not deliverable to the public Internet; onion does not replace public Internet email.
- Under `all`, outbound SMTP is undeliverable unless the recipients' MX hosts are in `direct.include`; every other non-TCP protocol needs a direct entry as well. Time sync works against the pre-filled servers only, and Tor itself needs a correct clock.
- `all` needs a dnsmasq built with `nftset` (2.87 or newer) for direct host names; CentOS Stream 10 ships one without it, so there the deploy refuses direct host names and accepts addresses and CIDRs only. `all` is also refused in swarm mode, on a dnsmasq other drop-ins share or whose `/etc/dnsmasq.conf` names its own upstreams, on a dnsmasq that resolves as root or nobody or shares its UID, when the Tor group already exists on the host, and when `networks.internet.dns` lies inside the resolver set.
- Roles that resolve through svc-dns-unbound get no clearnet answers under `all`, because unbound's upstream queries meet the DNS guard.
- Addresses resolved for direct names expire from the packet filter after an hour without a new lookup; a client that keeps an address longer sends new TCP connections through Tor and loses everything else.
- A direct host name on a shared CDN address opens that address for every site hosted there, and a direct name's CNAME target goes direct too.
- The TransPort listens on IPv4 only, so IPv6 TCP to destinations that are neither local nor direct is dropped under `all`, and IPv6 TCP to tor-listed addresses is dropped under `onion` and `all`.
- Under `onion`, a tor-listed address that is also a relay Tor needs loops into the TransPort, because Tor's group exemption exists under `all` only.
- Mirrors a host picks at runtime (Fedora metalink, Arch mirrorlist entries beyond the default) are not in the pre-fill; their traffic goes through Tor until they are added to `direct.include`.
- `none` is refused while a router an earlier `onion` or `all` deploy installed is still in place; the failure names the files and the nft table to remove first.
