# KeePassXC

## Description

[KeePassXC](https://keepassxc.org/) is a free, open-source, cross-platform password manager that stores credentials in an encrypted local database compatible with the KeePass format.

## Overview

This role installs the KeePassXC desktop application on Pacman-based workstations through the system package manager.
It is intended for personal-workstation roles in the desktop tier and does not configure databases, browser integrations, or autofill helpers.

## Features

- **Local-first vault:** Keeps the password database on the workstation, with no mandatory cloud sync.
- **Pacman integration:** Installs the upstream `keepassxc` package via the standard system package manager.
- **Workstation scope:** Targets the desktop tier (`desk-*`) and stays out of server inventories.
- **Minimal footprint:** Does not enable services or autostart entries beyond what the package itself provides.

## Further Resources

- [KeePassXC](https://keepassxc.org/)
- [KeePassXC documentation](https://keepassxc.org/docs/)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
