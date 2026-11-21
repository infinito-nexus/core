# Kernel parameters

## Description

[sysctl](https://man7.org/linux/man-pages/man8/sysctl.8.html) reads and writes Linux kernel parameters at runtime, and [sysctl.d](https://www.freedesktop.org/software/systemd/man/latest/sysctl.d.html) drop-ins persist them across reboots. A few parameters belong to a namespace, so each container has its own copy; every other one is global to the kernel, and a container that writes it changes the host.

## Overview

This role is the single place Infinito.Nexus sets kernel parameters. Each caller passes `sys_sysctl_owner` and a `sys_sysctl_parameters` dictionary; the role persists them in `/etc/sysctl.d/99-<owner>.conf` and applies them at once. The constructor stage calls it with the owner `host` and `SYS_SYSCTL_PARAMETERS`, the host-wide option an inventory MAY override. Its default entry is `kernel.core_pattern`: the systemd-coredump pipe where `/usr/lib/systemd/systemd-coredump` exists, and otherwise a file pattern in a dedicated root-owned directory under `/var/lib/infinito`.

Inside a container the role writes only the namespaced keys: `net.*`, the IPC keys `kernel.shm*`, `kernel.msg*`, `kernel.sem`, `kernel.sem_next_id` and `fs.mqueue.*`, and the UTS keys `kernel.hostname` and `kernel.domainname`. For every other key it writes neither the live value nor the drop-in, and it prints a skip line. A caller that moves its parameters out of an older file names that file in `sys_sysctl_retired_files`; the role removes the keys there only after the drop-in holds them and the live value is set.

## Features

- **One drop-in per owner:** every caller gets its own `/etc/sysctl.d/99-<owner>.conf`, sorted after the vendor files.
- **Persistent and immediate:** the drop-in survives a reboot, and the value is live on the first run.
- **Container-safe:** host-global keys are never written from inside a container, and the skip shows in the run output.
- **Core dumps out of the working directory:** cores go to systemd-coredump or to the dedicated directory; the role detects the handler and installs no package.
- **Migration without a gap:** keys leave a retired file only after the new drop-in is live.
- **Idempotent:** a second run reports no change.

## Developer Notes

- On Debian and Ubuntu, `systemd-coredump` is a separate optional package, and the `systemd` package ships `10-coredump-debian.conf` with `kernel.core_pattern=core`. On Fedora and CentOS Stream the handler belongs to `systemd-udev`, and on Arch to `systemd`.
- On Ubuntu, `apport` writes its own pattern when its service starts and writes `core` when it stops, so it can replace the host value until the next deploy.
- The owner `sysctl` is refused: `/etc/sysctl.d/99-sysctl.conf` is the distro symlink to `/etc/sysctl.conf`.
- On Fedora and CentOS Stream, `/etc/sysctl.d` itself belongs to `systemd-udev`, which a CentOS Stream container does not carry, and the sysctl module does not create the directory of its file. The role creates the drop-in directory before its first write.

## Further Resources

- [kernel.org sysctl/kernel](https://docs.kernel.org/admin-guide/sysctl/kernel.html)
- [freedesktop.org sysctl.d](https://www.freedesktop.org/software/systemd/man/latest/sysctl.d.html)
- [docs.ansible.com sysctl module](https://docs.ansible.com/ansible/latest/collections/ansible/posix/sysctl_module.html)
