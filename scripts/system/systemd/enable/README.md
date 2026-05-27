# systemd. Enable ✅

This directory contains platform-specific scripts for enabling systemd in environments where it is not active by default.
For the canonical Make target index that invokes these helpers, see [make.md](../../../../docs/contributing/tools/make.md).

---

## Scripts 📄

### `wsl2.sh` 🪟

Enables systemd as the WSL2 init system by writing `systemd=true` into `/etc/wsl.conf`.

- Silently exits if not running on WSL2
- Silently exits if systemd is already running (`/run/systemd/system` exists)
- If systemd is configured but not yet active, prints instructions to restart WSL2
- If systemd is not configured at all, appends the `[boot]` section to `/etc/wsl.conf` and triggers `wsl --shutdown` to apply the change

> ⚠️ After this script runs, WSL2 must be fully restarted before systemd-dependent steps (DNS, AppArmor, etc.) will work.

---

## Related 🔗

- [`../`](../). systemd administration scripts
