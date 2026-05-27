# sys-ctl-hlth-btrfs

## Description

Checks the health of all mounted Btrfs filesystems by inspecting device error counters.

## Overview

This role health-check for Btrfs filesystems, alerts on any device error counters.

## Features

- Iterates over every Btrfs filesystem.
- Runs `btrfs device stats` and alerts if any error counters are non-zero.
- Hooks into systemd and a timer for regular checks.
- On failure, calls `sys-ctl-alm-compose.infinito@…` for notification.

## Usage

Just include this role in your playbook; it will:

1. Deploy a small shell script
2. Install a `.service` and `.timer` unit.
3. Send alerts via `sys-ctl-alm-compose` if any filesystem shows errors.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
