# Incus

## Description

[Incus](https://linuxcontainers.org/incus/) is a manager for system containers and virtual machines. It runs QEMU/KVM virtual machines with their own kernel, stores their disks in copy-on-write storage pools and exposes everything through a REST API that clients reach with TLS client certificates.

## Overview

This role turns a Debian or Arch host into the local hypervisor for agent VM workspaces. It installs Incus, refuses a host without `/dev/kvm`, creates the agent storage pool on a copy-on-write driver and an agent bridge without NAT, and creates one restricted project `agents-<instance>` per Infinito.Nexus instance. The agent broker (`svc-ai-agent-broker`) clones one VM per task from the agent VM template into that project and destroys it when the task ends.

## Features

- **Hardware virtualization only:** The deploy refuses a host without `/dev/kvm` and says how to enable VT-x, AMD-V or nested virtualization.
- **Copy-on-write clones:** The agent storage pool uses btrfs, zfs or an lvm thin pool; the `dir` driver is refused because it copies the whole disk per clone.
- **Capacity check:** The deploy refuses a host whose free memory or storage is below the warm pool plus `agents.max_running` times the largest agent VM size plus the reserve in `services.incus.agents.reserve`.
- **Restricted project:** `agents-<instance>` allows unprivileged instances only, pool-managed disks only (no host path), managed network cards on the agent bridge only and no low-level VM options.
- **Agent bridge:** `services.incus.network` is a bridge without NAT and without IPv6, so a VM leaves the host only through the egress proxy the agent firewall compiles.
- **Broker channel:** Secrets and tool calls reach a VM over vsock, through the Incus agent inside the VM, and only after the broker assigned the VM to a task; never through cloud-init, the instance configuration or a file in the template.
- **Secure boot:** The zfs kernel module of the template is built by DKMS and is not signed, so the agent project's default profile sets `security.secureboot` to `services.incus.agents.secure_boot`, `false` by default.

## API Listener

`services.incus.api.enabled` (default `false`) sets `core.https_address` to `services.incus.api.listen` (default `[::]:8443`); with it off, the deploy unsets the key and the API stays on the local socket. The role's nftables table `infinito_svc_virt_incus` drops every connection to that port whose source is not in `services.incus.api.allowed_sources`: the egress addresses of the provision runner and, in a test deployment, of the e2e stack. An empty list admits no one. The deploy stores the fields `endpoint` (`INCUS_API_ENDPOINT`, `https://<host>:<port>`), `certificate` (the server certificate) and `fingerprint` (its SHA-256) in OpenBao at `platform/data/provision/incus-<host>`; the provision runner takes `endpoint` as `INCUS_ADDR` and pins `certificate` instead of trusting the server blindly. The endpoint is read inside containers, the provision runner and the Playwright container, where a loopback name points at the container itself, so a `<host>` in `NETWORK_LOOPBACK_HOSTS` (the dev stack's `localhost`) is recorded as `host.docker.internal`, which both containers pin to the host; any other `<host>` is recorded as it stands and must resolve from a container. The pinned certificate also sets the name the client checks: it trusts that one certificate and checks its first DNS name, so the name in the endpoint does not have to match it. `core.remote_token_expiry` is `services.incus.remote_token_expiry` (`1h`), so a join token issued by hand for another client dies unused.

## Workspace Projects

With `services.incus.workspaces.enabled` on, `workspace apply` creates the project `ws-<id>` and `workspace destroy` removes it:

- **Virtual machines only:** `ws-<id>` carries the restrictions of the agents project and adds `limits.containers` 0, because a container shares the host kernel with the other services of the host.
- **Plan limits:** `services.incus.workspaces.limits` sets `limits.instances`, `limits.cpu`, `limits.memory` and `limits.disk`. The default profile gives each instance `services.incus.workspaces.instance` as its size, a root disk in the agent storage pool and a NIC with `security.mac_filtering`, `security.ipv4_filtering` and `security.ipv6_filtering`, so an instance sends from its own addresses only.
- **Restricted certificate:** The platform runner generates the workspace's client key pair inside its task and writes the certificate and the private key to `tenant/data/ws-<id>-provision/incus`. The Incus host receives the certificate only, through `incus config trust add-certificate --restricted --projects ws-<id>` on the local socket, so the trust entry reaches `ws-<id>` alone and no join token for a workspace exists.
- **Destroy:** `workspace destroy` refuses while `ws-<id>` holds an instance, and otherwise removes the trust entry, the project, its bridge and the OpenBao key.

## Routed Subnet

The provider routes a public IPv4 and IPv6 subnet to the host, named by `services.incus.workspaces.subnet.ipv4` and `.ipv6`; with workspaces on and either one unset, the deploy refuses to run. Each workspace gets its own bridge `wsbr<11 hex of the id>` with a `/28` IPv4 and a `/64` IPv6 slice of them (`services.incus.workspaces.slice`), the gateway on the first address, `ipv4.nat` and `ipv6.nat` false and stateful DHCPv6. The host routes the addresses and holds no NAT rule and no network forward for an instance. The role's nftables table forwards nothing between two workspace bridges, nor between a workspace bridge and the agent bridge.

## Further Resources

- [Incus documentation](https://linuxcontainers.org/incus/docs/main/)
- [Incus project restrictions](https://linuxcontainers.org/incus/docs/main/reference/projects/)
