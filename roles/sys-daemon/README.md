# sys-daemon

## Description

Role to reset and configure the **systemd manager** for Infinito.Nexus.  
It ensures a clean state of the manager configuration and applies default timeout values.

## Overview

- Purges the systemd manager drop-in directory if requested.  
- Validates all active unit files before reload/reexec.  
- Applies default timeout values for systemd manager behavior.  
- Provides handler-based reload/reexec for systemd.  

## Features

- **Drop-in Purge:** Optionally remove `/etc/systemd/system.conf.d` contents.  
- **Manager Defaults:** Deploys custom timeouts via `timeouts.conf`.  
- **Validation:** Uses `systemd-analyze verify` before reload.  
- **Integration:** Triggers `daemon-reload` or `daemon-reexec` safely.  

## Further Resources

- [systemd - Manager Configuration](https://www.freedesktop.org/software/systemd/man/systemd-system.conf.html)  
- [systemd-analyze](https://www.freedesktop.org/software/systemd/man/systemd-analyze.html)  
- [systemctl](https://www.freedesktop.org/software/systemd/man/systemctl.html)
