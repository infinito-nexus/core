# sys-ctl-hlth-journalctl

## Description

Scans `journalctl` over the last day for “error” entries and alerts if any are found.

## Overview

This role searches the systemd journal for errors over the past day and alerts if any are found.

## Features

- Runs `journalctl --since '1 day ago' | grep -i error`.
- Exits non-zero on matches.
- Scheduled via systemd timer.
- Alerts via `sys-ctl-alm-compose` on detection.

## Usage

Include the role; set `on_calendar_health_journalctl` for your preferred schedule.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
