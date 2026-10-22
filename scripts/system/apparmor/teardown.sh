#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/system/apparmor/common.sh
source "${SCRIPT_DIR}/common.sh"

echo "[apparmor] tearing down (dev mode)"

if ! apparmor_should_manage; then
	echo "[apparmor] skipping teardown: $(apparmor_skip_reason)"
	exit 0
fi

if apparmor_service_exists; then
	systemctl stop apparmor || true # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
else
	echo "[apparmor] apparmor.service not available or systemd inactive; skipping service stop"
fi

APPARMOR_FS=/sys/kernel/security/apparmor
if [[ -w "${APPARMOR_FS}/.remove" ]]; then
	mapfile -t profiles < <(apparmor_removable_profiles <"${APPARMOR_FS}/profiles")
	for profile in "${profiles[@]}"; do
		printf '%s' "${profile}" >"${APPARMOR_FS}/.remove"
	done
	echo "[apparmor] unloaded ${#profiles[@]} profile(s); docker-default stays loaded"
else
	echo "[apparmor] ${APPARMOR_FS}/.remove is not writable; skipping profile unload"
fi

echo "[apparmor] teardown complete"
