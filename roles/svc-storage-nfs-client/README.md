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
