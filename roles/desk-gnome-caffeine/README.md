# GNOME Caffeine

## Description

This role installs [caffeine-ng](https://codeberg.org/WhyNotHugo/caffeine-ng), a utility that prevents your GNOME desktop from entering sleep mode or activating the screensaver automatically. It also ensures that caffeine-ng is set to autostart at user login.

## Overview

This role installs caffeine-ng and configures it to autostart for preventing screen sleep on GNOME.

## Purpose

The purpose of this role is to ensure uninterrupted workflow by keeping the desktop active during long-running tasks or presentations. By automatically starting caffeine-ng, it prevents unwanted screen locking or sleep modes on GNOME systems.

## Features

- Installs caffeine-ng from the AUR using an AUR helper.
- Creates the autostart directory if it does not exist.
- Deploys a customized desktop entry to ensure caffeine-ng starts automatically.
- Enhances user experience by maintaining an active desktop environment.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
