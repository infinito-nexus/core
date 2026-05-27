# Package Manager Installation

## Description

This Ansible role installs [Kevin's Package Manager](https://github.com/kevinveenbirkenbach/package-manager) and updates packages using `pkgmgr` on Arch Linux systems. It provides a unified interface for package installation and update management, ensuring consistent deployment across environments.

## Overview

The role abstracts package management operations using `pkgmgr`. It ensures the package manager itself is updated once per run and provides idempotent installation and update routines for specified packages.

## Purpose

The purpose of this role is to automate the installation and update process for Infinito.Nexus-related applications or other managed packages using `pkgmgr`. It simplifies package handling and enforces best practices for package deployment in automated environments.

## Features

- **Automatic pkgmgr Update:** Ensures the package manager is always up-to-date.
- **Idempotent Package Installation:** Only installs packages when necessary.
- **Flexible Notification:** Supports handler notification for post-install actions (e.g., Docker Compose builds).
- **Optional Privilege Escalation:** Controlled via the `pkgmgr_become` variable (default: `true`).

## Role Variables

| Name            | Description                                                     | Default |
|-----------------|-----------------------------------------------------------------|---------|
| `package_name`   | Name of the package to install/update                          | (required) |
| `package_notify` | Handler to notify on package installation/update              | "" |

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
