# NFS Client

## Description

[NFS](https://en.wikipedia.org/wiki/Network_File_System) (Network File
System) lets a host mount a directory exported by a remote server as if
it were a local filesystem. The client packages provide the kernel
helpers and userspace tools to perform that mount.

## Overview

This role installs the distro-appropriate NFS client packages on every
host in the Ansible group `svc-swarm-node` and probe-mounts the
configured `storage.nfs.server` and the export base from the
svc-storage-nfs-server services.yml SPOT to confirm
reachability and writability at deploy time. The actual docker volume
mounts happen later, driven by the Docker engine at container start.

## Features

- **Distro-aware packages:** Installs `nfs-common` on Debian/Ubuntu,
  `nfs-utils` on Arch / RHEL / Fedora / Alpine.
- **Ephemeral probe mount:** Mounts the export, writes a marker, then
  unmounts; failures surface immediately at deploy time, never at first
  container boot.
- **Strict assertion:** Missing `storage.nfs.server` or
  fails the deploy with a precise error.
- **Node-local backups:** After the state mount, binds the node's own
  `/var/lib/infinito-backup` over `/var/lib/infinito/backup`, so every
  backup repository on a swarm node is written to local disk with its
  extended attributes, and the backup host pulls it from there.
  Generations written to the share before the bind stay under the
  export's `backup/` directory, hidden from the nodes; remove them there
  by hand.
- **Directory delegations off against old ganesha:** When the server
  runs nfs-ganesha older than 9.11, every client and the controller set
  the kernel's `nfsv4` parameter `directory_delegations` to `N`, at
  runtime and in `/etc/modprobe.d`. The parameter is kernel-wide, so on
  a lab whose nodes share one kernel it covers every NFS mount of that
  host until the module reloads.
