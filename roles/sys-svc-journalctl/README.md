# Journalctl

This Ansible role manages the configuration of `systemd-journald` on target hosts.

## Description

- Copies a customized `journald.conf` to `/etc/systemd/journald.conf`  
- Ensures log retention for one week  
- Restarts the `systemd-journald` service when configuration changes  
- Supports live log streaming via `journalctl -f`

## Overview

1. **Template deployment**  
   The role places your `journald.conf.j2` template into `/etc/systemd/journald.conf`.
2. **Service handler**  
   On change, it notifies a handler to restart `systemd-journald`.
3. **Monitoring**  
   You can follow logs in real time with `journalctl -f`.

## Features

- Customizable retention and runtime limits  
- Seamless restarts on config update  
- Integration with `sys-ctl-hlth-journalctl` for downstream monitoring

## Usage

```yaml
- hosts: all
  roles:
    - role: sys-svc-journalctl

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
