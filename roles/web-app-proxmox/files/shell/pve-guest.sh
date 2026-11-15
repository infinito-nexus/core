#!/bin/sh
# Param PROXMOX_GUEST_DIR: volume whose ssh/config pins the guest's host key and names the launcher's key.
# Param $@: the command to run as root inside the Proxmox VE guest; every PROXMOX_* variable travels along.
set -eu
exec ssh -F "$PROXMOX_GUEST_DIR/ssh/config" guest "$@"
