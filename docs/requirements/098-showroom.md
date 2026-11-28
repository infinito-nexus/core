# 098 - Showroom servers for customer demo instances

## User Story

As an operator who presents Infinito.Nexus to a prospective customer, I want one isolated server per customer project on an existing host, reachable under that project's demo domains, so that I can deploy a full demo instance against it without buying or setting up hardware.

## Decisions

- **Hypervisor:** [Incus](https://linuxcontainers.org/incus/) on the host, no Proxmox.
- **Flavor:** every project runs a virtual machine by default. A project MAY set `flavor: container` in its entry under `services.showroom.projects`, which runs an Incus system container with nesting instead.
- **Scope:** the role only provides the servers. It never deploys Infinito.Nexus into them; the operator deploys against them like against any other host.
- **Budget:** `services.showroom.budget.memory` caps the memory of all projects together. The role ships `16GiB`.
- **Routing:** the host's reverse proxy terminates TLS for every domain of a project and forwards the request to that project's server (L7). SNI passthrough is out of scope, because every vhost on the host terminates port 443 itself.
- **Access:** the operator reaches a project's server with an SSH ProxyJump through the host. The server accepts the keys listed in the project entry.
- **Zero trust on the host (operator decision 2026-11-11):** root on the host stays locked. The ProxyJump runs as `incus-bastion`, a user without shell or TTY that may only forward to port 22 of the showroom servers. The break-glass path runs as `incus-operator`, which may execute exactly one sudo command per server (`incus exec --project <project> <server> -- /bin/bash -l`) and needs its SSH key plus its own password for it. No user stays in `incus-admin`, so the host administrator reaches Incus only through its own sudo password. A per-project Incus trust certificate is out of scope, because the showroom projects are not `restricted` and such a client could start a privileged container.
- **First project:** Karakalpak (`karakalpakstan.demo.infinito.nexus`) on echoserver, set in the inventory, not in the role.

## Acceptance Criteria

- [ ] A role `svc-virt-showroom` installs Incus on an Arch Linux or Debian host and refuses every other distribution with a message naming the supported ones.
- [ ] The role creates one Incus bridge with IPv4 NAT on the subnet the role's network allocation assigns, and one storage pool.
- [ ] On a host running Docker, a server reaches the internet through the bridge before its first boot and after every restart of Docker, because the role inserts `DOCKER-USER` accept rules for the bridge in both directions.
- [ ] For every entry of `services.showroom.projects` the role creates one Incus project and one instance named after the entry, with the entry's CPU, memory and disk limits and a fixed IPv4 address on the bridge.
- [ ] A project with flavor `vm` on a host without `/dev/kvm` fails the deploy with a message that names the project and the `container` flavor as the way out.
- [ ] A project list whose memory sum exceeds `services.showroom.budget.memory` fails the deploy before any instance is created, naming every project and its memory.
- [ ] The instance accepts SSH logins for the keys of its project entry, so `ssh -J <host> root@<address>` reaches it.
- [ ] The host's reverse proxy serves every domain of a project with a certificate of the host and proxies each request, Host header and WebSocket upgrade included, to port 443 of that project's server.
- [ ] `ssh -J incus-bastion@<host> root@<address>` reaches a server, while `incus-bastion` gets no shell, no TTY, no remote forward and no forward to any other address or port.
- [ ] `incus-operator` opens a root shell in a server only through `sudo incus exec --project <project> <server> -- /bin/bash -l` with its own password; any other sudo command is refused.
- [ ] After the deploy the group `incus-admin` has no members.
- [ ] A host inventory without a key for `incus-bastion` or `incus-operator`, or without a password for `incus-operator`, fails the deploy with a message naming the user.
- [ ] A second deploy with an unchanged project list reports no change.
- [ ] Unit tests cover the budget check, the KVM check, the rendered proxy configuration, the instance limits, the bastion `Match` block and the operator's sudo rule; each fails without the code it covers.
- [ ] The role README documents the project entry, the ProxyJump inventory lines for a project's server and the routing.
