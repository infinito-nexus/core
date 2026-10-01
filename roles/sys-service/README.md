# sys-service

## Description

Role to manage **systemd service units** for Infinito.Nexus software stacks.
It installs or removes unit files, configures runtime behavior, and ensures services are properly deployed.

## Overview

- Resets service units by removing old or obsolete definitions.
- Deploys new service unit files and service scripts.
- Optionally sets up timers linked to the services.
- Ensures correct reload/restart behavior across the stack.
- Provides the shared `files/debug.sh` SPOT for reusable service-failure diagnostics.
- Exposes `tasks/utils/debug.yml` as the canonical Ansible wrapper around that script.

## Features

- **Unit Cleanup:** Automated removal of old service units.
- **Custom Templates:** Supports both `systemctl.service.j2` and `systemctl@.service.j2`.
- **Timers:** Integrates with `sys-timer` for scheduled execution.
- **Runtime Limits:** Configurable `RuntimeMaxSec` per service.
- **Handlers:** Automatic reload/restart of services when definitions change.
- **Shared Diagnostics:** Centralized `systemctl`/`journalctl`/unit-file diagnostics via `files/debug.sh`.
- **Wrapper Task:** Reusable Ansible include in `tasks/utils/debug.yml` for calling and printing the shared diagnostics.

## Further Resources

- [systemd - Service Units](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [systemd - Timer Units](https://www.freedesktop.org/software/systemd/man/systemd.timer.html)
- [systemctl](https://www.freedesktop.org/software/systemd/man/systemctl.html)
