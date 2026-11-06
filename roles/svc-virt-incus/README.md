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

## Further Resources

- [Incus documentation](https://linuxcontainers.org/incus/docs/main/)
- [Incus project restrictions](https://linuxcontainers.org/incus/docs/main/reference/projects/)
