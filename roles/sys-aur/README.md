# System AUR Helper

## Description

This role ensures that the AUR helper [yay](https://github.com/Jguer/yay) is installed on the system. It installs yay via [pacman](https://wiki.archlinux.org/title/Pacman) and creates a dedicated `aur_builder` user to facilitate building AUR packages.

## Overview

The role performs the following tasks:

- Installs the AUR helper [yay](https://github.com/Jguer/yay) using pacman.
- Creates an `aur_builder` user with a home directory and adds the user to the wheel group.
- Grants the `aur_builder` user passwordless [sudo](https://en.wikipedia.org/wiki/Sudo) rights for running pacman.

## Purpose

The primary purpose of this role is to streamline AUR package management on Arch Linux systems by ensuring that the required AUR helper is installed and properly configured.

## Features

- **Yay Installation:** Installs the AUR helper [yay](https://github.com/Jguer/yay) on Arch Linux.
- **User Creation:** Creates a dedicated `aur_builder` user.
- **Sudo Configuration:** Grants passwordless sudo rights to `aur_builder` for pacman.

## Further Resources

- [ansible-aur](https://github.com/kewlfft/ansible-aur)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
