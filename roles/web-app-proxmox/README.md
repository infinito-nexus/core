# Proxmox VE

## Description

[Proxmox VE](https://www.proxmox.com/en/products/proxmox-virtual-environment/overview) is an open-source virtualization platform built on Debian. It runs QEMU/KVM virtual machines, manages their storage, networks and resource pools, and serves a web UI and a REST API with fine-grained, pool-scoped permissions and API tokens.

## Overview

This role runs Proxmox VE as one Docker container, in a data center or locally, as the hypervisor for agent VM workspaces. It builds its own image from the official Debian base and the official `pve-no-subscription` repository at the pinned `services.proxmox.ve.version`, uses no third-party image and changes nothing about the subscription notice. The web UI is served at its own domain through the front proxy, and the agent broker (`svc-ai-agent-broker`) drives the agent VMs through a pool-scoped API token over the internal address.

## Features

- **Official packages only:** The image adds the Proxmox VE archive key from `enterprise.proxmox.com`, verifies it against `services.proxmox.ve.keyring_sha512`, adds the `pve-no-subscription` repository of `download.proxmox.com` and installs every package of `services.proxmox.ve.packages` at its pinned version. The build refuses an empty checksum or an unpinned package. There is no third-party image and no subscription workaround.
- **Compose only:** `meta/services.yml` enables compose mode and disables swarm, because the container owns the KVM device and the VM disks of one host.
- **Separate host:** The deploy refuses a host that also runs `web-app-keycloak`, `svc-ai-litellm` or `web-app-openbao`, in its own groups or on another inventory host with the same address, unless the inventory sets `services.proxmox.shared_host` to `true`.
- **Hardware virtualization only:** The deploy refuses a host without `/dev/kvm` and says how to enable it.
- **Sized limits:** The deploy refuses container limits (`cpus`, `mem_limit`) below the warm pool plus `agents.max_running` times the largest agent VM size plus `services.proxmox.agents.overhead`, and a host whose free memory or storage is below that demand plus `services.proxmox.agents.reserve`.
- **Front proxy and group gate:** The UI is reached only through the front proxy on port 443, behind an OAuth2 proxy that admits only members of this role's administrator group. The SSO flags turn on as soon as any inventory host runs `web-app-keycloak`, and the deploy refuses to run while they resolve to false.
- **No onion:** The deploy refuses to run while `services.tor.enabled` resolves to true, so the hypervisor UI never gets an onion address.
- **Backup scope:** The backup covers the cluster configuration (`proxmox_config`, the `pmxcfs` database) and the ISO and container templates (`proxmox_templates`, `/var/lib/vz/template`). Everything under `/var/lib/vz/images` (`proxmox_vm_disks`) is not backed up: that covers the agent VM disks, which are destroyed when their task ends, and the base disks of the agent VM templates, which `make agents-vm-template` rebuilds.
- **Broker channel:** Secrets and tool calls reach an agent VM through the QEMU guest agent, and only after the broker assigned the VM to a task; never through cloud-init, the VM configuration or a snippet.

## Devices, capabilities and namespaces

The container runs systemd and the Proxmox VE services without `privileged`. Each grant in `templates/compose.yml.j2` and its reason:

- **`/dev/kvm`:** QEMU starts the agent VMs with hardware virtualization; without it they would run emulated and too slowly to serve a task.
- **`/dev/net/tun`:** QEMU attaches each VM network card as a tap device on the VM bridge inside the container.
- **`/dev/vhost-net`:** the in-kernel virtio network backend for those tap devices, so VM traffic is not copied through QEMU.
- **`/dev/fuse`:** `pmxcfs` mounts the cluster file system at `/etc/pve` through FUSE; every Proxmox VE service reads its configuration there.
- **`NET_ADMIN`:** creates the VM bridge `services.proxmox.vm_network.bridge`, its tap ports and the firewall rules that keep VM traffic on that bridge.
- **`SYS_ADMIN`:** systemd mounts its own file systems and `pmxcfs` mounts `/etc/pve`.
- **`cgroup: private`:** systemd and QEMU manage their own cgroup subtree, in the container's own cgroup namespace, not the host's.
- **Host namespaces:** none of network, PID or IPC; the container keeps its own. It has no user namespace of its own unless the Docker daemon runs with `userns-remap`, so root in the container is root on the host.

The container publishes one port: the web UI port 8006 as `127.0.0.1:7992` (`services.proxmox.ports.local.http`) for the front proxy. Ports 3128, 111, 5405 and 22 are never published.

## Known gaps

- **TLS upstream:** `pveproxy` on port 8006 speaks only HTTPS, but the OAuth2 proxy (`web-app-keycloak` `sso_proxy` templates) and the front proxy location (`sys-svc-proxy`) reach the upstream over plain HTTP, and this role cannot change that scheme through its own meta. Until those shared templates take an HTTPS upstream, the web UI does not load through the front proxy.
- **Console websocket:** the noVNC and xterm.js consoles need a websocket location; the role sets no websocket proxy flavour yet.

## Broker token

The broker gets one privilege-separated API token per Infinito.Nexus instance, bound to one resource pool. Its role holds exactly these privileges, on that pool and on the agent storage only:

- `VM.Allocate`, `VM.Clone`, `VM.Audit`, `VM.PowerMgmt`
- `VM.Config.CPU`, `VM.Config.Memory`
- `VM.GuestAgent.Audit`, `VM.GuestAgent.FileRead`, `VM.GuestAgent.FileWrite`, `VM.GuestAgent.Unrestricted`
- `Datastore.AllocateSpace`, `Datastore.Audit` on the agent storage
- `Pool.Audit` on the agent pool

`VM.Config.Network`, `VM.Config.Disk`, `VM.Config.HWType`, `Sys.*` and every privilege outside the pool are left out, so the token cannot move a VM to another bridge, add a host or foreign-storage disk, or touch a VM outside the pool.

## Further Resources

- [Proxmox VE documentation](https://pve.proxmox.com/pve-docs/)
- [Proxmox VE package repositories](https://pve.proxmox.com/wiki/Package_Repositories)
- [Proxmox VE user management](https://pve.proxmox.com/wiki/User_Management)
