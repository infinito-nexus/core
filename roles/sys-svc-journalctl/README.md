# Journalctl

This Ansible role manages the configuration of `systemd-journald` on target hosts.

## Description

- Copies a customized `journald.conf` to `/etc/systemd/journald.conf`  
- Keeps the journal persistent (`Storage=persistent`)  
- Raises the journald rate limit of `docker.service`, which every container logs through, with a drop-in configured by `docker_rate_limit` in `meta/services.yml`; `sys-svc-container` writes it through `tasks/utils/docker_rate_limit.yml` before Docker first starts, and a host whose Docker already runs picks it up at its next Docker start  
- Keeps journal entries at most `max_retention_sec`, one week by default (`meta/services.yml`)  
- Caps the persistent journal (`SystemMaxUse=`) at `system_max_use_percent` of the filesystem holding `/var/log/journal`, 2 % by default, and leaves `system_keep_free` of that filesystem free, 15 % by default (`meta/services.yml`)  
- Restarts the `systemd-journald` service when configuration changes, then flushes the runtime journal (`journalctl --flush`): a restarted journald keeps writing to `/run/log/journal` until it gets a flush request, which otherwise comes only from `systemd-journal-flush.service` at the next boot, so a host that booted with a volatile journal would keep it until then  
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
```
