# NFS Server

## Description

[NFS](https://en.wikipedia.org/wiki/Network_File_System) (Network File
System) is a kernel-level protocol for sharing files over a network.
The server exports a directory tree under defined access rules; clients
mount it as if it were a local filesystem.

## Overview

This role installs an NFS server in one of two flavors, the distro kernel
server or userspace nfs-ganesha, selected per deployment. Both export the
swarm state path to the resolved addresses of the `svc-swarm-node` group and
to an additional CIDR allow-list; ganesha also exports the export base and
squashes root there. Export options come from `vars/main.yml` for the kernel
flavor and from the ganesha configuration template for ganesha. NFS server
HA, Kerberos integration, and client-side mounting are out of scope; client
mounts are handled by `svc-storage-nfs-client`.

## Features

- **Distro-aware install:** Installs `nfs-kernel-server` on Debian /
  Ubuntu, `nfs-utils` on Arch / RHEL / Fedora / Alpine.
- **Inventory-driven ACL:** Allowed-IP list derives from the
  `svc-swarm-node` group; unrelated hosts cannot mount.
- **Reload-on-change:** Re-running the role overwrites `/etc/exports`
  with the current allowed-IP set; the handler reloads via
  `exportfs -ra` only when the file changed.
