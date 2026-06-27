# NFS Server

## Description

[NFS](https://en.wikipedia.org/wiki/Network_File_System) (Network File
System) is a kernel-level protocol for sharing files over a network.
The server exports a directory tree under defined access rules; clients
mount it as if it were a local filesystem.

## Overview

This role installs the distro-appropriate NFS kernel server, exports
`storage.nfs.export_base` (default `/srv/nfs`), and restricts access to
inventory members of the `svc-swarm-node` group. The export options
default to `rw,sync,no_subtree_check,root_squash,no_all_squash`. NFS
server HA, Kerberos integration, and client-side mounting are out of
scope; client mounts are handled by `svc-storage-nfs-client`.

## Features

- **Distro-aware install:** Installs `nfs-kernel-server` on Debian /
  Ubuntu, `nfs-utils` on Arch / RHEL / Fedora / Alpine.
- **Inventory-driven ACL:** Allowed-IP list derives from the
  `svc-swarm-node` group; unrelated hosts cannot mount.
- **Reload-on-change:** Re-running the role overwrites `/etc/exports`
  with the current allowed-IP set; the handler reloads via
  `exportfs -ra` only when the file changed.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
