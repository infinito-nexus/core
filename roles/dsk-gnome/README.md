# GNOME Desktop

## Description

This role aggregates various GNOME desktop components to ensure a cohesive and fully functional GNOME environment on Arch Linux. It includes the installation and configuration of several sub-roles:

- **dsk-gnome-caffeine:** Prevents the system from sleeping or locking automatically.
- **dsk-gnome-extensions:** Manages GNOME Shell extensions and installs the CLI GNOME Extension Manager.
- **dsk-gnome-terminal:** Installs GNOME Terminal, the official terminal emulator for GNOME.

## Overview

This role aggregates essential GNOME desktop roles (including caffeine, extensions, and terminal) for a complete GNOME environment on Linux.

## Purpose

The purpose of this role is to provide a complete GNOME desktop experience by orchestrating multiple sub-roles. This simplifies deployment and management by ensuring that all key components are installed and configured in a consistent, system-wide manner.

## Features

- Aggregates multiple GNOME-related roles into one cohesive setup.
- Installs and configures caffeine-ng to keep the desktop active.
- Manages GNOME Shell extensions and integrates the CLI GNOME Extension Manager.
- Installs GNOME Terminal for a robust command-line interface.
- Ensures a seamless and uniform GNOME environment on Arch Linux.

## Addons

Role-level GNOME Shell extensions are declared in `meta/addons/` (unified addon contract, requirement 026).
They are installed through `cli-gnome-extension-manager`, which receives the `action`, `uuid`, and `url` from each addon's `config` payload:

| Addon | Mechanism | Default state | Bridges |
|-------|-----------|---------------|---------|
| `nasa-apod` | `extension` | required (always enabled) | none |
| `dash-to-dock` | `extension` | optional, disabled by default | none |
| `dash-to-panel` | `extension` | required (always enabled) | none |

These are desktop GNOME Shell extensions with no in-app web surface to drive, so they are exempt from the Playwright requirement (requirement 026, Decision 11).
