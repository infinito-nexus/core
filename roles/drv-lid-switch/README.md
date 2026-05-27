# LID Switch Driver

## Description

The lid switch is a hardware component on laptops that triggers power state changes (sleep, hibernate, lock) when the lid is closed. On Linux, systemd's `logind` daemon manages lid switch events via `/etc/systemd/logind.conf`. The [`setup-hibernate`](https://github.com/kevinveenbirkenbach/setup-hibernate) tool provides hibernation support configuration.

## Overview

This role addresses a common issue on Linux laptops: closing the lid while docked or plugged in leads to unintended sleep or hibernation. It installs the necessary hibernation tools and updates `/etc/systemd/logind.conf` to:

- Hibernate on lid close when on battery
- Lock the session when on AC power or docked

## Purpose

The purpose of this role is to enforce a consistent and predictable lid switch behavior across power states, improving usability on laptops that otherwise behave unpredictably when the lid is closed.

## Features

- **Installs `setup-hibernate`:** Uses `pkgmgr` to install and initialize hibernation support.
- **Systemd Integration:** Applies proper `logind.conf` settings for lid switch handling.
- **Power-aware Configuration:** Differentiates between battery, AC power, and docked state.
- **Idempotent Design:** Ensures safe re-runs and minimal unnecessary restarts.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
