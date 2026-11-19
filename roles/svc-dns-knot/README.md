# Knot DNS

## Description

[Knot DNS](https://www.knot-dns.cz/) is an authoritative DNS server with built-in DNSSEC signing, zone transfers and dynamic updates.

## Overview

This role deploys Knot DNS as the authoritative server of the Semaphore workspace subzone, `services.semaphore.workspaces.dns.zone` of `web-app-semaphore`. It is the default `knot` DNS flavor.

## Features

- **Signed primary:** The first host of the role's group is the primary. It loads the zone file, signs the zone with DNSSEC (`dnssec-signing`, policy `ecdsap256sha256`) and notifies every further host of the group.
- **Secondaries by signed transfer:** Every further host runs a secondary that takes the signed zone by zone transfer from the primary. Transfers and notifies are signed with the TSIG key `transfer` (`secrets.credentials.transfer_tsig_secret`, hmac-sha256).
- **Public port 53:** Each server publishes port 53 over UDP and TCP on its host (`ports.public.dns`), so resolvers reach it on `networks.internet.ip4`.
- **Canary record:** The zone file holds the SOA, one NS and glue record per host and the TXT canary `_canary`, which the Playwright suite reads from every server.

## Workspace keys

[tasks/workspace.yml](./tasks/workspace.yml) takes `WORKSPACE` (`ws-<uuid>`) and `WORKSPACE_ACTION`:

- `apply` creates the hmac-sha512 TSIG key `ws-<uuid>.<subzone>.` on the primary, adds one ACL with `action: update`, `update-owner: key`, `update-owner-match: sub-or-equal` and `update-type` A, AAAA, CNAME and TXT, reloads the server, and writes `server`, `port`, `key_name`, `key_algorithm` and `key_secret` to `tenant/data/ws-<uuid>-provision/dns` through `web-app-openbao` `utils/kv.yml`. So a workspace key changes only names at or below its own name, and only the provision runner of that workspace reads it.
- `destroy` removes the key and its ACL, reloads the server and deletes that OpenBao key.

The primary keeps the workspace keys in `workspaces.json` of its instance directory, mode `0600`; `apply` keeps an existing key. The keys and the transfer secret reach `knot.conf` only, which is rendered with mode `0400` under the masking of every credential task.

## Host requirements

Port 53 of the host must be free on every address, so a host stub resolver such as the one of `systemd-resolved` must not listen on it. The one exception is a compose host that also runs `svc-net-tor`: its `.onion` split-DNS forwarder holds port 53 on the loopback and docker bridge addresses, so there knot binds port 53 on `networks.internet.ip4` only, which must then be an address of a host interface. A swarm port carries no host address, so in swarm port 53 of the node must stay free on every address. `svc-dns-unbound` publishes no host port; its consumers reach it on its own network. The delegation of the subzone (its NS, glue and DS records in the parent zone) is written by the platform deploy, not by this role.

The swarm test lab cannot meet this: every lab node runs its own resolver on port 53. Swarm lab rounds therefore publish knot on port 1053 ([lab_ports.py](../../utils/tests/swarm/lab_ports.py)); compose and production keep port 53.

## Tests

- [test_acl.py](../../tests/unit/python/roles/svc-dns-knot/test_acl.py) renders `knot.conf` for a primary and a secondary and proves the update grants, the signing and the transfer, with negative controls.
- [files/playwright/test-subzone.js](./files/playwright/test-subzone.js) queries every server of the group with the DNSSEC OK bit and expects the same signed canary from each.
