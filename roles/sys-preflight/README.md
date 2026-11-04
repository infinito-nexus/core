# Pre-flight

## Description

A pre-flight check probes a host before a deploy changes it and stops the deploy when the host is in a state the deploy cannot recover from on its own: a kernel without its modules, a full disk, a docker object that belongs to another project, a port a host service already holds, or a domain that does not resolve.

## Overview

This role runs the pre-flight checks of Infinito.Nexus. The constructor stage in `tasks/stages/01_constructor.yml` includes it on every host after the shared services are placed and before any package is installed.

The role runs while `VALIDATE` is true, which by default follows `DEBUG`; `--validate true` turns it on without debugging, `--validate false` on `infinito administration deploy dedicated` skips it together with the inventory validation. Each check has its own switch under `preflight.checks.<check>.enabled` in `meta/services.yml`, and every switch is on by default.

## Features

- **Kernel modules:** On a host outside a container, fails when the running kernel has no module index under `/usr/lib/modules` or `/lib/modules`, so Docker could not create its iptables chains after a restart (`kernel`).
- **Clock:** On a host outside a container, waits up to two minutes for chrony or timedatectl to report a synchronised clock (`clock`).
- **Disk space:** Fails when `/` or the Docker root directory is fuller than `SIZE_PERCENT_MAXIMUM_DISK_USAGE` and offers less than `SIZE_GB_MINIMUM_DISK_FREE` (`disk`).
- **Docker networks:** Fails when a network named after an entity holds a subnet outside the block its role declares, carries the compose label of another project, or occupies a subnet another role declares. A network without a compose label, or labelled with a declaring role id, passes on its subnet (`networks`).
- **Docker containers:** Fails when a container a role declares carries no compose or stack label naming its entity (`containers`).
- **Docker volumes:** Fails when a volume a role declares is labelled with another project. A volume without any label, or labelled with a declaring role id, passes (`volumes`).
- **Address pools:** Fails when a `default-address-pools` entry in `/etc/docker/daemon.json` overlaps a role subnet, `NETWORK_MESH_POOL` or `NETWORK_TOR_VIRTUAL_CIDR` (`pools`).
- **Public ports:** Fails when a host process outside Docker listens on a public port the deploy binds (`ports`).
- **Clearnet domains:** Fails when a clearnet domain the deploy serves on the host does not resolve through `getent hosts` (`domains`).
- **Inventory validation:** The deploy CLI validates the inventory before Ansible starts unless `--validate false` is given or `inventory` is switched off (`inventory`).

## Usage

Switch a check off for one host in its inventory:

```yaml
applications:
  sys-preflight:
    services:
      preflight:
        checks:
          ports:
            enabled: false
```

The deploy CLI reads the `inventory` switch from this role's `meta/services.yml` before Ansible starts, so an inventory override does not reach it; edit `meta/services.yml` to switch the inventory validation off.
