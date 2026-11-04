#!/usr/bin/env bash

# shellcheck disable=SC2034
APPARMOR_UNCONFINED_RESTRICTION_SYSCTL=/proc/sys/kernel/apparmor_restrict_unprivileged_unconfined
# shellcheck disable=SC2034
APPARMOR_UNCONFINED_RESTRICTION_STATE=/run/infinito/apparmor-restrict-unprivileged-unconfined

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

# Param: $1 sysctl file of kernel.apparmor_restrict_unprivileged_unconfined
# Param: $2 state file that keeps the value found before lifting it
apparmor_lift_unconfined_restriction() {
	local sysctl="$1"
	local state="$2"
	local current=""

	if [[ ! -e "${sysctl}" ]]; then
		apparmor_log "[apparmor] ${sysctl} absent; containers are not stacked onto unconfined"
		return 0
	fi

	current="$(tr -d '[:space:]' <"${sysctl}")"
	if [[ "${current}" == "0" ]]; then
		apparmor_log "[apparmor] unprivileged-unconfined restriction already off"
		return 0
	fi

	mkdir -p "$(dirname "${state}")"
	printf '%s\n' "${current}" >"${state}"
	printf '0\n' >"${sysctl}"
	apparmor_log "[apparmor] lifted unprivileged-unconfined restriction (was ${current}); containers keep plain docker-default"
}

# Param: $1 sysctl file of kernel.apparmor_restrict_unprivileged_unconfined
# Param: $2 state file written by apparmor_lift_unconfined_restriction
apparmor_reinstate_unconfined_restriction() {
	local sysctl="$1"
	local state="$2"

	if [[ ! -f "${state}" ]]; then
		apparmor_log "[apparmor] no lifted unprivileged-unconfined restriction to reinstate"
		return 0
	fi

	tr -d '[:space:]' <"${state}" >"${sysctl}"
	rm -f "${state}"
	apparmor_log "[apparmor] reinstated unprivileged-unconfined restriction"
}

systemd_is_operational() {
	command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]
}

apparmor_service_exists() {
	systemd_is_operational || return 1
	systemctl list-unit-files apparmor.service --no-legend 2>/dev/null | grep -q '^apparmor\.service'
}
