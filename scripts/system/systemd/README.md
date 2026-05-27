# systemd Administration Scripts ⚙️

This directory contains scripts for managing systemd across different platforms and environments used in Infinito Nexus development.
For the canonical Make target index that invokes these helpers, see [make.md](../../../docs/contributing/tools/make.md).

---

## Subdirectories 📁

### [`enable/`](enable/) ✅

Platform-specific scripts for enabling systemd where it is not active by default.

- **`wsl2.sh`**. enables systemd as the WSL2 init system via `/etc/wsl.conf` and restarts WSL2 if needed

---
