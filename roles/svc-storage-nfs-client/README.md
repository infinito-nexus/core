# NFS Client

## Description

[NFS](https://en.wikipedia.org/wiki/Network_File_System) (Network File
System) lets a host mount a directory exported by a remote server as if
it were a local filesystem. The client packages provide the kernel
helpers and userspace tools to perform that mount.

## Overview

This role installs the distro-appropriate NFS client packages on every
host in the Ansible group `svc-swarm-node` and probe-mounts the
configured `storage.nfs.server:storage.nfs.export_base` to confirm
reachability and writability at deploy time. The actual docker volume
mounts happen later, driven by the Docker engine at container start.

## Features

- **Distro-aware packages:** Installs `nfs-common` on Debian/Ubuntu,
  `nfs-utils` on Arch / RHEL / Fedora / Alpine.
- **Ephemeral probe mount:** Mounts the export, writes a marker, then
  unmounts; failures surface immediately at deploy time, never at first
  container boot.
- **Strict assertion:** Missing `storage.nfs.server` or
  `storage.nfs.export_base` fails the deploy with a precise error.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
