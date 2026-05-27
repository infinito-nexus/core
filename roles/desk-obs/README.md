# OBS Studio

## Description

[OBS Studio](https://obsproject.com/) is a free, open-source application for video recording and live streaming, widely used for screencasts, broadcasting, and content creation.

## Overview

This role installs the OBS Studio desktop application on Pacman-based workstations through the system package manager.
It targets the desktop tier and does not configure scenes, capture devices, or streaming profiles.

## Features

- **Streaming and recording:** Provides the upstream OBS Studio binary for both live broadcasting and local recording.
- **Pacman integration:** Installs the `obs-studio` package via the standard system package manager.
- **Workstation scope:** Targets the desktop tier (`desk-*`) and stays out of server inventories.
- **No state changes beyond install:** Does not enable services or write per-user OBS configuration.

## Further Resources

- [OBS Studio](https://obsproject.com/)
- [OBS Studio knowledge base](https://obsproject.com/kb/)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
