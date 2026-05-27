# sys-ctl-hlth-disc-space

## Description

Monitors disk-space usage and alerts if any filesystem usage exceeds your defined threshold.

## Overview

This role disk-space usage monitor; alerts when usage exceeds threshold.

## Features

- Uses `df` to gather current usage.
- Compares against `size_percent_disc_space_warning` threshold.
- Sends failure alerts via `sys-ctl-alm-compose`.
- Runs on a configurable systemd timer.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
