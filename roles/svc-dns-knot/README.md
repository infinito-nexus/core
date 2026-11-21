# Knot DNS

## Description

[Knot DNS](https://www.knot-dns.cz/) is an authoritative DNS server with built-in DNSSEC signing, zone transfers and dynamic updates.

## Overview

This role deploys Knot DNS as the authoritative server of the Semaphore workspace subzone, `services.semaphore.workspaces.dns.zone` of `web-app-semaphore`. It is the default `knot` DNS flavor.

## Features

- **Signed primary:** The first host of the role's group is the primary. It loads the zone file, signs the zone with DNSSEC (`dnssec-signing`, policy `ecdsap256sha256`) and notifies every further host of the group.
- **Secondaries by signed transfer:** Every further host runs a secondary that takes the signed zone by zone transfer from the primary. Transfers and notifies are signed with the TSIG key `transfer` (`secrets.credentials.transfer_tsig_secret`, hmac-sha256).
- **Public port 53:** Each server publishes port 53 over UDP and TCP on its host (`ports.public.dns`), so resolvers reach it on `networks.internet.ip4`.
- **Canary record:** The zone file holds the SOA, one NS and glue A record per host and the TXT canary `_canary`, which the Playwright suite reads from every server.

## Workspace keys

[tasks/workspace.yml](./tasks/workspace.yml) takes `WORKSPACE` (`ws-<uuid>`) and `WORKSPACE_ACTION`:

- `apply` creates the hmac-sha512 TSIG key `ws-<uuid>.<subzone>.` on the primary, adds one ACL with `action: update`, `update-owner: key`, `update-owner-match: sub-or-equal` and `update-type` A, AAAA, CNAME and TXT, reloads the server, and writes `server`, `port`, `key_name`, `key_algorithm` and `key_secret` to `tenant/data/ws-<uuid>-provision/dns` through `web-app-openbao` `utils/kv.yml`. So a workspace key changes only names at or below its own name, and only the provision runner of that workspace reads it.
- `destroy` removes the key and its ACL, reloads the server and deletes that OpenBao key.

The primary keeps the workspace keys in `workspaces.json` of its instance directory, mode `0600`; `apply` keeps an existing key. The keys and the transfer secret reach `knot.conf` only, which is rendered with mode `0400` under the masking of every credential task.

## Delegation

The `knot` DNS flavor step of `web-app-semaphore`, [flavors/dns/knot/delegate.yml](../web-app-semaphore/tasks/flavors/dns/knot/delegate.yml), writes the delegation of the subzone into its parent Cloudflare zone: the longest active Cloudflare zone the token reads whose name is a proper suffix of the subzone, which the step asks the Cloudflare zones API for, so a deploy domain that is a Cloudflare zone of its own takes the delegation. A name with only a pending or moved zone is no parent, as such a zone answers no query. No such zone fails the deploy, and so does a parent name that carries a second zone of any status, which the Cloudflare records role could not tell apart. [flavors/dns/knot.yml](../web-app-semaphore/tasks/flavors/dns/knot.yml) includes the step behind its gates, as Ansible templates `delegate_to` and `loop` before a task's `when` but evaluates the `when` of an include before it loads the file. The step runs in the platform deploy on the stack host when `DNS_PROVIDER` is `cloudflare` and this role ran on the primary in the same deploy, never in a workspace task and never under the `route53` or `cloudflare` flavor:

- **Records:** The filters of [knot_delegation.py](../../plugins/filter/knot_delegation.py) build them from every host of the group, the primary first, named as in the zone file: one NS `ns<n>.<subzone>` per host, its glue A from `networks.internet.ip4`, and the DS. They are global filters, because the flavor step runs in `web-app-semaphore`, which does not load the plugins of this role. There is no AAAA glue and no AAAA in the zone file: knot listens on `0.0.0.0@53` only, so it answers no IPv6 query. A host without an IPv4 address, or with a loopback one, fails the deploy.
- **DS:** `knot_ksk` reads `keymgr -j <subzone> list` on the primary and picks the current KSK, the newest ready KSK that is not retiring, against `now().timestamp()`: Ansible's `now()` is naive local time, which `timestamp()` reads as local, so that is the epoch in every controller time zone, where `now(utc=true)` would shift by the offset; `knot_ds` takes its SHA-256 DS from `keymgr <subzone> ds`. During a KSK rollover that is the new KSK, so the DS follows the rollover on the next platform deploy. A DS output without that key tag fails the deploy rather than publishing a DS that would make the subzone bogus.
- **Idempotence:** Every record goes through `sys-dns-cloudflare-records`, whose `cloudflare_records_converged` skips every record the zone already holds: first the NS and glue, then in a run of its own the DS, which replaces every other DS of the subzone. An NS record of a host that left the group stays until it is removed by hand.
- **Submission:** The `subzone` policy sets no `ksk-submission`, so Knot keeps a new KSK ready until it is confirmed by hand. Once the DS stands, the step runs `knotc zone-ksk-submitted <subzone>` on the primary while the current KSK is not yet active, so that KSK turns active and a KSK it replaces retires. `knot_submission` judges its result: `no key ready for submission` passes unchanged, and any other error fails the deploy, also one knotc prints with exit status 0.

## Host requirements

Port 53 of the host must be free on every address, so a host stub resolver such as the one of `systemd-resolved` must not listen on it. The one exception is a compose host that also runs `svc-net-tor`: its `.onion` split-DNS forwarder holds port 53 on the loopback and docker bridge addresses, so there knot binds port 53 on `networks.internet.ip4` only, which must then be an address of a host interface. A swarm port carries no host address, so in swarm port 53 of the node must stay free on every address. `svc-dns-unbound` publishes no host port; its consumers reach it on its own network. The delegation of the subzone (its NS, glue and DS records in the parent zone) is written by the platform deploy, see [Delegation](#delegation).

The swarm test lab cannot meet this: every lab node runs its own resolver on port 53. Swarm lab rounds therefore publish knot on port 1053 ([lab_ports.py](../../utils/tests/swarm/lab_ports.py)); compose and production keep port 53.

## Tests

- [test_acl.py](../../tests/unit/python/roles/svc-dns-knot/test_acl.py) renders `knot.conf` for a primary and a secondary and proves the update grants, the signing and the transfer, with negative controls.
- [test_knot_delegation.py](../../tests/unit/python/plugins/filter/test_knot_delegation.py) proves the NS, glue and DS records of the knot filters against the zone file and `keymgr` output, no AAAA while knot listens on IPv4 only, every record against the argument checks of `cloudflare_dns`, the active parent zone and the rollover, with negative controls.
- [test_knot_flavor.py](../../tests/unit/python/roles/web-app-semaphore/test_knot_flavor.py) proves that the flavor step templates nothing of the knot group before its gates, that its filters load without this role, its clock in every controller time zone, the order of the role runs and the KSK confirmation, with negative controls.
- [files/playwright/test-subzone.js](./files/playwright/test-subzone.js) queries every server of the group with the DNSSEC OK bit and expects the same signed canary from each.
