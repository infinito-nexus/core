#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/system/apparmor/common.sh
source "${SCRIPT_DIR}/common.sh"

echo "[apparmor] restoring profiles"

if ! apparmor_should_manage; then
	echo "[apparmor] skipping restore: $(apparmor_skip_reason)"
	exit 0
fi

apparmor_reinstate_unconfined_restriction "${APPARMOR_UNCONFINED_RESTRICTION_SYSCTL}" "${APPARMOR_UNCONFINED_RESTRICTION_STATE}"

if apparmor_service_exists; then
	systemctl start apparmor
	systemctl enable apparmor
else
	echo "[apparmor] apparmor.service not available or systemd inactive; skipping service start"
fi

if command -v apparmor_parser >/dev/null 2>&1 && compgen -G '/etc/apparmor.d/*' >/dev/null; then
	apparmor_parser -r /etc/apparmor.d/*
else
	echo "[apparmor] no AppArmor profiles found to reload"
fi

echo "[apparmor] restore complete"
