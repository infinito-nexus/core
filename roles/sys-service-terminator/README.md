# sys-service-terminator

## Description

Runs a collected list of systemd services at the **end of a play**.
This is useful for services where flush/restart is suppressed during setup,
but should be started once everything they depend on is ready.

## Overview

This role runs a collected list of systemd services at the end of a play.

## Features

- **Automated provisioning:** Configured by Ansible without manual steps.

## How it works

- Consumes `system_service_run_list` (created by `sys-service` when `system_service_force_flush_final=true`).
- Enables and starts/restarts each service.
- Shows diagnostics (`systemctl status`, `journalctl -xeu`) on failure.

## Variables

- `system_service_run_list` (list): list of systemd unit names to run
- `SYS_SERVICE_RUNNER_STATE` (string): desired state (`started`, `restarted`, ...)  

## Further Resources

- <https://www.freedesktop.org/software/systemd/man/systemctl.html>

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
