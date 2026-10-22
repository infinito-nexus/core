#!/usr/bin/env bash

apparmor_log() {
	printf '%s\n' "$*"
}

apparmor_warn() {
	printf '%s\n' "$*" >&2
}

apparmor_is_installed() {
	command -v apparmor_parser >/dev/null 2>&1 ||
		command -v aa-status >/dev/null 2>&1 ||
		command -v aa-enabled >/dev/null 2>&1 ||
		[[ -d /etc/apparmor.d ]]
}

apparmor_is_enabled() {
	if command -v aa-enabled >/dev/null 2>&1; then
		aa-enabled >/dev/null 2>&1 && return 0
	fi

	if [[ -r /sys/module/apparmor/parameters/enabled ]]; then
		local enabled=""
		enabled="$(tr -d '[:space:]' </sys/module/apparmor/parameters/enabled 2>/dev/null || true)"
		[[ "${enabled}" =~ ^[Yy1]$ ]] && return 0
	fi

	return 1
}

apparmor_skip_reason() {
	if ! apparmor_is_installed; then
		printf 'AppArmor userspace is not installed.'
	elif ! apparmor_is_enabled; then
		printf 'AppArmor is not enabled.'
	else
		printf ''
	fi
}

apparmor_should_manage() {
	apparmor_is_installed && apparmor_is_enabled
}

apparmor_removable_profiles() {
	sed -E 's/ \([a-z]+\)$//' | grep -v -E '//|^docker-default$'
}

systemd_is_operational() {
	command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]
}

apparmor_service_exists() {
	systemd_is_operational || return 1
	systemctl list-unit-files apparmor.service --no-legend 2>/dev/null | grep -q '^apparmor\.service'
}
