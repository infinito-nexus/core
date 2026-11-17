# Tor Onion Service

## Description

Runs a [Tor](https://www.torproject.org/) daemon on the node and publishes a Tor v3 onion service, turning an Infinito.Nexus instance behind NAT/CGNAT into a fully Tor-reachable node without a public IP, port forwarding, VPS, or DynDNS.

## Overview

When `svc-net-tor` is deployed, the node runs in the `multi` network mode by default: every role with a Tor bond keeps its clearnet domains and gains one `<sub>.<node>.onion` sibling per domain, each served by its own vhost. `NETWORK_MODE: tor` serves those roles on onion only (see [network_modes.md](../../docs/contributing/design/network_modes.md)). The Tor daemon runs on the host network of every node (a global service in swarm), binds `127.0.0.1` and that node's docker bridge, and only the stack host publishes the hidden service, which maps to the host OpenResty (`HiddenServicePort 80 -> <backend host>:80`, where the backend host `TOR_HS_BACKEND_HOST` is the docker bridge address in compose, `127.0.0.1` when there is none, and the stack host's default IPv4 address in swarm); per-app subdomains (`<app>.<node>.onion`) are routed by the `Host` header. Onion vhosts serve plain HTTP (onion v3 already provides transport encryption and server authentication), so apps behind them receive `X-Forwarded-Proto: http`.

The onion key is minted offline during the inventory build and kept beside the checkout that deploys, while the inventory carries only the address, so the address is stable across redeploys and restorable from a backup (see [Node address](#node-address)).

## Features

- **Onion siblings:** the node keeps its clearnet `DOMAIN_PRIMARY`; every role with a Tor bond gains a `<sub>.<node>.onion` sibling of each of its domains, and `NETWORK_MODE: tor` serves those roles on the onion only.
- **Single key, per-app subdomains:** one hidden service serves every app at `<app>.<node>.onion`, Host-routed by OpenResty.
- **Offline deterministic minting:** the v3 key is generated without running Tor and the inventory pins its address (stable, backupable, restorable).
- **HTTP on the onion side:** TLS is forced off for `.onion` (no Let's Encrypt possible); onion v3 crypto is the transport auth.
- **Listener guard:** every node that runs Tor loads a packet filter that drops SocksPort packets from outside the internal ranges and from sources that would not route back through the interface they arrived on, in every route. The nodes that run the egress router guard their TransPort, DNSPort and dnsmasq the same way.
- **Chutney test net:** the `chutney` flavor builds one private Tor network into the tor image for the whole deployment. The node that holds its address (the stack host, loopback in compose) runs the network's authorities and relays on the port bases `services.tor.chutney` declares, and every node's Tor joins it. The listener guard admits only internal sources to those ports.
- **Egress route:** `services.tor.egress.route` (`TOR_EGRESS_ROUTE`) decides where outbound traffic goes; inbound stays onion plus the clearnet siblings either way.
  - `none` leaves egress alone: no resolver, no redirect, no TransPort. Both lists must be empty.
  - `onion` (default) resolves and routes `.onion` through Tor and leaves everything else direct.
  - `all` sends every outbound connection of the node and its containers through Tor and fails closed: TCP goes to the TransPort, every other protocol to an unlisted destination is dropped, and names outside the direct list resolve only through Tor's DNSPort. DNS reaches only loopback, the bridge and the deployed roles' own subnets, so no LAN resolver answers beside Tor; systemd-resolved, resolv.conf and the docker daemon lose their clearnet fallback. When Tor is down, that traffic fails; there is no clearnet fallback. Compose only.
- **Tor and direct lists:** `egress.tor` and `egress.direct` each carry an `include` and an `except`; entries are host names, `*.` wildcards, IPs and CIDRs. A host name covers its subdomains, so `example.org` and `*.example.org` mean the same. `except` only narrows its own `include`, a destination both lists keep takes Tor, and the route decides everything no list matches. `.onion` can never be direct.
- **Infrastructure pre-fill:** `direct.include` defaults to the package mirrors and time servers of the supported distributions, the registries (and their blob hosts) of every image the deployed applications pull, and the ACME endpoint, all declared under `egress.infrastructure`. These services see the node's own address; replace or empty the list in the inventory to change that.

## Node address

When `svc-net-tor` is among the deployed applications, the inventory build mints the node onion offline: [tor_node.py](../../cli/administration/inventory/provision/tor_node.py) calls `cli.administration.inventory.onion`, which writes `hostname`, `hs_ed25519_public_key` and `hs_ed25519_secret_key` to `.onion-identity/hs/` at the root of the checkout that deploys, and the build writes the address into `applications.svc-net-tor.services.tor.node` of the host's `host_vars`. A later build reuses the files, so the address does not change. To mint or print the address without a build, run from the checkout root:

```bash
python3 -m cli.administration.inventory.onion init-env --env-file .env
```

The command creates the files only when `.onion-identity/hs/hostname` is missing and prints the address either way. Git ignores `.onion-identity/`, so the key never enters a commit. Every deploy copies the three files into `<DIR_VAR_LIB_NODE>/svc-net-tor/data/infinito/node/` on the stack host and overwrites what it finds there, so Tor serves exactly the minted address. Tor's data and config directories live under `DIR_VAR_LIB_NODE` on each node's own disk, not under the `DIR_VAR_LIB` that swarm nodes share over NFS: every node renders its own torrc and runs its own Tor, and two Tor processes cannot share one data directory. Moving those directories keeps the address, because the keys come from `.onion-identity/hs/` on every deploy; once the stack runs on the new directories, the deploy removes what an earlier deploy left under `<DIR_VAR_LIB>/svc-net-tor/`, so the old key copy leaves the shared export and the backups taken of it. The hosts that mount the NFS export (members of both `svc-swarm-node` and `svc-storage-nfs-client`) share that tree, so one of them removes it, the stack host when it mounts the export; every other node removes its own local tree. The removal is skipped when that tree is, or contains, the live data directory, by device and inode or after resolving symlinks.

### Backup and restore

Whoever holds `hs_ed25519_secret_key` can serve the address, so back up `.onion-identity/hs/` of the deploying checkout as a secret, with the same care as the inventory vault password. To rebuild or move the node, restore that directory into the new checkout before the inventory build: the build reuses it, `services.tor.node` keeps the old address, and the deploy installs the keys on the node. Without the directory the next build mints a new address, and every onion URL changes.

## Limitations

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
- `none` is refused while the dnsmasq drop-in an earlier `onion` or `all` deploy installed is still in place; the failure names the steps that remove it. A leftover router packet filter needs no manual step: the deploy replaces it by the listener guard in one nft load.
- The `chutney` net admits internal sources only, so nodes that reach the stack host over a public address cannot join it.
