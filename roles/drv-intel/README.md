# Intel Driver

## Description

This Ansible role installs the Intel VA-API media driver for the current Linux distribution.

## Overview

Package name differs across distributions:

- Arch Linux: `intel-media-driver`
- Debian/Ubuntu: `intel-media-va-driver`
- Fedora: `libva-intel-media-driver`
- CentOS Stream 9: `libva-intel-hybrid-driver` (via EPEL)

## Features

- Idempotent installation of Intel media drivers  
- Supports Arch, Debian, Ubuntu, Fedora, CentOS Stream  

## Further Resources

- [Intel Media Driver upstream documentation](https://01.org/intel-media-sdk)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
