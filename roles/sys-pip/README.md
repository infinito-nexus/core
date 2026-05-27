# Python-Pip

## Description

This role installs the [python-pip](https://en.wikipedia.org/wiki/Pip_(package_manager)) package on the target system. It ensures that the pip package manager is available for installing Python packages.

## Overview

Optimized for simplicity and idempotency, this role:

- Installs the python-pip package using [pacman](https://wiki.archlinux.org/title/Pacman).
- Sets a flag to ensure the installation tasks run only once.

## Purpose

The primary purpose of this role is to provide a reliable installation of the Python package manager, pip, ensuring that subsequent Python package installations can proceed without issues.

## Features

- **Pip Installation:** Installs python-pip if not already present.
- **Idempotency:** Ensures tasks are executed only once.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
