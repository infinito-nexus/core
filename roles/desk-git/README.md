# Git

## Description

This role installs and configures Git on the target system using the Pacman package manager (via the community.general.pacman module). In addition, it configures Git for the user by installing a custom git configuration using the [git-configurator](https://github.com/kevinveenbirkenbach/git-configurator) tool. The role ensures that Git is installed and that the configuration tasks are run only once per host.

## Overview

This role installs Git and configures it using a custom git-configurator for personal computers.

## Purpose

The purpose of this role is to automate the installation and configuration of Git for personal computers. By leveraging a custom git-configurator, it sets up essential Git settings such as merge options, rebase preferences, user information, and GPG signing, ensuring a consistent environment for version control operations.

## Features

- **Automated Git Installation:** Installs Git using Pacman.
- **Custom Git Configuration:** Invokes the git-configurator tool to merge user-specific configuration options.
- **Idempotent Task Execution:** Uses host-level run-once artifacts to ensure that configuration tasks are executed only once per host.
- **Integration:** Works alongside the pkgmgr role to streamline overall system setup.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
