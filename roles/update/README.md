# Package update

## Description

Operating-system package managers such as [apt](https://wiki.debian.org/Apt),
[pacman](https://wiki.archlinux.org/title/pacman) and
[dnf](https://dnf.readthedocs.io/) keep installed software in sync with their
upstream distribution repositories. Each one ships with a different command
surface but they all serve the same goal: refresh the index and upgrade every
installed package on the host.

## Overview

This role refreshes the package index and upgrades every installed package on
the host. `tasks/main.yml` reads `ansible_facts['distribution']` and dispatches
to one of three task files grouped by package-manager family. Debian and
Ubuntu both use `apt`, Fedora and CentOS both use `dnf`, so each pair shares a
single task file. A separate `unsupported.yml` fails loudly with a clear
message when a host runs a distribution that this role does not yet cover.

| `ansible_facts['distribution']` | Task file         | Module                     |
| ------------------------------- | ----------------- | -------------------------- |
| `Archlinux`                     | `arch.yml`        | `community.general.pacman` |
| `Debian` / `Ubuntu`             | `debian.yml`      | `ansible.builtin.apt`      |
| `Fedora` / `CentOS`             | `fedora.yml`      | `ansible.builtin.dnf`      |
| anything else                   | `unsupported.yml` | `ansible.builtin.fail`     |

## Features

- **Per-family dispatch:** Routes by `ansible_facts['distribution']` so the
  caller never has to gate the role with a `when:` clause.
- **Five-distro coverage:** Supports the five default CI distros (Archlinux,
  Debian, Ubuntu, Fedora, CentOS) without duplicated task code.
- **Loud on unsupported hosts:** Fails with a clear message instead of
  silently skipping when the host runs an unmapped distribution.
- **Once-per-play idempotency:** Wraps the dispatch in
  `when: run_once_update is not defined` and writes the flag via
  `tasks/utils/once/flag.yml`, so repeated invocations within one play are
  no-ops.

## Developer Notes

To extend support for a new distribution, add the distribution name to the
lookup dict in [main.yml](./tasks/main.yml). When the new distribution shares
a package manager with an existing entry, point it at that entry's task file.
When it brings a new package manager, add a new family file under
[tasks/](./tasks/) and keep [meta/main.yml](./meta/main.yml) `platforms` in
sync.

## Further Resources

- [apt](https://wiki.debian.org/Apt)
- [pacman](https://wiki.archlinux.org/title/pacman)
- [dnf](https://dnf.readthedocs.io/)
- [community.general.pacman](https://docs.ansible.com/ansible/latest/collections/community/general/pacman_module.html)
- [ansible.builtin.apt](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/apt_module.html)
- [ansible.builtin.dnf](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/dnf_module.html)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
