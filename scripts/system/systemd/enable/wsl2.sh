#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/meta/env/load.sh
source "${SCRIPT_DIR}/../../../meta/env/load.sh"
[[ "${INFINITO_IS_WSL2}" == "true" ]] || exit 0

# /run/systemd/system only exists when systemd is actually running as PID 1
if [ -d /run/systemd/system ]; then
	exit 0
fi

# systemd not running — check if we already wrote the config
if grep -qs "systemd=true" /etc/wsl.conf 2>/dev/null; then
	echo ">>> systemd is configured but not yet active."
	echo ">>> Close ALL open Ubuntu terminals, then run in Windows PowerShell:"
	echo ">>>"
	echo ">>>   wsl --shutdown"
	echo ">>>"
	echo ">>> Then reopen Ubuntu and run: make environment-bootstrap"
	exit 1
fi

echo ">>> WSL2 detected — systemd is not enabled."
echo ">>> Enabling systemd in /etc/wsl.conf..."

if grep -qs "^\[boot\]" /etc/wsl.conf 2>/dev/null; then
	sudo sed -i '/^\[boot\]/a systemd=true' /etc/wsl.conf
else
	printf '\n[boot]\nsystemd=true\n' | sudo tee -a /etc/wsl.conf >/dev/null
fi

echo ">>> Restarting WSL2 to apply changes..."
echo ">>> Please reopen this terminal and run: make environment-bootstrap"

/mnt/c/Windows/System32/wsl.exe --shutdown 2>/dev/null || {
	echo ""
	echo ">>> Could not auto-restart WSL2."
	echo ">>> Run this in Windows PowerShell, then re-run make environment-bootstrap:"
	echo ">>>   wsl --shutdown"
}
