# Showroom

## Description

[Incus](https://linuxcontainers.org/incus/) is a manager for system containers and virtual machines. It runs QEMU/KVM virtual machines with their own kernel and system containers that share the host kernel, and gives every instance its own limits, disks and network cards.

## Overview

This role turns an Arch Linux or Debian host into a showroom: one isolated server per customer demo project, reachable under that project's demo domains. It installs Incus, applies one bridge with IPv4 NAT on the subnet in `meta/networks.yml` and one storage pool, and creates one Incus project with one instance per entry of `services.showroom.projects`. It never deploys Infinito.Nexus into a server; the operator deploys against it like against any other host.

## Features

- **One server per project:** Every entry of `services.showroom.projects` gets its own Incus project and one instance named after the entry, with the entry's CPU, memory and root disk limits and a fixed IPv4 address on the showroom bridge.
- **Virtual machine by default:** A project runs a virtual machine unless it sets `flavor: container`, which runs a system container with `security.nesting=true` so Docker runs inside.
- **Memory budget:** The deploy refuses a project list whose memory sum exceeds `services.showroom.budget.memory` (`16GiB` by default) before any instance is created, naming every project and its memory.
- **KVM check:** A `vm` project on a host without `/dev/kvm` fails the deploy with a message naming the project and `flavor: container` as the way out.
- **SSH keys and clock:** cloud-init installs `openssh-server`, `systemd-timesyncd` and the entry's `ssh_authorized_keys` for root on first boot. The cloud image ships no time sync, and the Infinito.Nexus preflight inside the server waits for `NTPSynchronized=yes`. Password logins go off through the drop-in `/etc/ssh/sshd_config.d/60-showroom.conf`, not through `ssh_pwauth`: that key writes `sshd_config` before `openssh-server` exists, the package then keeps the minimal file without `UsePAM yes`, and sshd refuses the key login of the locked root account.
- **Egress next to Docker:** Docker sets the FORWARD policy to DROP, which cuts the servers off the internet (cloud-init's package install, apt, image pulls) while SSH from the host and the proxy hop keep working. Before the first server boots, a oneshot unit inserts two `DOCKER-USER` rules for the showroom bridge (forward from it, return traffic to it), and it runs again on every start of `docker.service`. On a host without Docker the unit changes nothing.
- **Layer 7 routing:** The host's reverse proxy terminates TLS for every domain of a project with the host's certificate and forwards each request, Host header and WebSocket upgrade included, to port 443 of the project's server. The hop is HTTPS with the original host name as SNI and without certificate verification, because the demo instance inside the server answers with its own self-signed certificate. SNI passthrough is out of scope, because every vhost on the host terminates port 443 itself.
- **Zero-trust access on the host:** Two users with the least rights replace the host administrator on the way into a server, and root on the host stays locked. `incus-bastion` has no shell and no TTY; an sshd `Match` block lets it forward to port 22 of the showroom servers and nowhere else, and it cannot listen on the host. `incus-operator` may run exactly one command per server through sudo with its own password, `incus exec --project <project> <server> -- /bin/bash -l`, as the break-glass path when SSH into a server fails. The role empties the group `incus-admin`, so no user drives Incus without that password; the host administrator reaches it only through its own sudo password. Both users need at least one key in `users.<name>.authorized_keys` of the host's inventory, or the deploy fails.
- **Idempotent:** A second deploy with an unchanged project list reports no change; a changed CPU, memory, disk size or address is set on the existing instance.

## Use cases

### Project entry

| Field | Meaning |
| --- | --- |
| `flavor` | `vm` (default) or `container`. |
| `image` | A cloud-init capable image, such as `images:debian/12/cloud`. |
| `cpus` | `limits.cpu` of the instance. |
| `memory` | `limits.memory` of the instance, such as `12GiB`. |
| `disk` | Size of the root disk, such as `60GiB`. |
| `address` | Fixed IPv4 address on the showroom bridge (`192.168.245.0/24`, the host is `.1`). |
| `domains` | Every FQDN the host proxies to this server. |
| `ssh_authorized_keys` | Public keys root accepts. |

The certificate and the DNS records are issued from `domains.canonical` before any role runs, so the inventory lists every project domain there as well. The deploy refuses a mismatch between both lists.

```yaml
applications:
  svc-virt-showroom:
    domains:
      canonical:
        - karakalpakstan.demo.infinito.nexus
        - auth.karakalpakstan.demo.infinito.nexus
    services:
      showroom:
        projects:
          karakalpak:
            flavor: vm
            image: images:debian/12/cloud
            cpus: 4
            memory: 12GiB
            disk: 80GiB
            address: 192.168.245.10
            domains:
              - karakalpakstan.demo.infinito.nexus
              - auth.karakalpakstan.demo.infinito.nexus
            ssh_authorized_keys:
              - ssh-ed25519 AAAA... operator@workstation
```

### Inventory of a project's server

The server has no public address. The operator reaches it with an SSH ProxyJump through the showroom host's jump user, so its inventory entry points at the bridge address and jumps through the host:

```yaml
karakalpak:
  ansible_host: 192.168.245.10
  ansible_user: root
  ansible_ssh_common_args: "-J incus-bastion@echoserver.example"
```

The same works by hand with `ssh -J incus-bastion@echoserver.example root@192.168.245.10`. When SSH into the server is broken, the break-glass path is `ssh -t incus-operator@echoserver.example sudo incus exec --project karakalpak karakalpak -- /bin/bash -l`.

The host's inventory names the keys of both access users:

```yaml
users:
  incus-bastion:
    authorized_keys:
      - ssh-ed25519 AAAA... operator@workstation
  incus-operator:
    authorized_keys:
      - ssh-ed25519 AAAA... operator@workstation
```

## Further resources

- [Incus documentation](https://linuxcontainers.org/incus/docs/main/)
- [Incus instance options](https://linuxcontainers.org/incus/docs/main/reference/instance_options/)
- [cloud-init documentation](https://cloudinit.readthedocs.io/)
