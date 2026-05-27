# Arduino Development Utilities

## Description

This Ansible role installs everything needed for Arduino development on Arch Linux. It includes the official Arduino IDE, documentation, and user group configurations to enable serial port access for uploading code to boards.

Learn more at the [Arduino Project Website](https://www.arduino.cc/), [Arch Wiki - Arduino](https://wiki.archlinux.org/title/Arduino), and on [Wikipedia](https://en.wikipedia.org/wiki/Arduino).

## Overview

Building upon the general developer persona, this role focuses on embedded and microcontroller development. It ensures that the system has the correct packages and permissions to work with Arduino boards via USB.

## Purpose

The role enables a ready-to-use Arduino development setup by installing necessary tools and configuring user permissions for serial access.

## Features

- **Installs Arduino IDE & Docs:** Provides GUI and offline references.
- **User Group Configuration:** Adds the developer to `uucp` and `lock` groups for serial communication.
- **Persona Integration:** Extends `dev-core` with embedded-specific tools.

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
