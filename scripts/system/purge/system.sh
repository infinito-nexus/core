#!/usr/bin/env bash
set -euo pipefail

usage() {
	cat <<'EOF'
Usage:
  system.sh [--help]

Runs the repository's full cleanup pass used by make system-purge.
Includes git state, Docker, host caches, and Windows cleanup.

The routine is best-effort:
- skips commands that are not available on the current host
- continues after individual cleanup failures
- keeps the one-time Windows Disk Cleanup profile setup optional

Optional one-time Windows setup:
  PURGE_WINDOWS_CLEANMGR_SETUP=true system.sh
EOF
}

case "${1:-}" in
-h | --help)
	usage
	exit 0
	;;
esac

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"

cd "${REPO_ROOT}"

if [[ -f "scripts/meta/env/load.sh" ]]; then
	# shellcheck source=scripts/meta/env/load.sh
	source "scripts/meta/env/load.sh"
fi

log() {
	echo ">>> $*"
}

warn() {
	echo "!!! WARNING: $*" >&2
}

overall_rc=0

command_exists() {
	local cmd="$1"

	if [[ "${cmd}" == /* ]]; then
		[[ -e "${cmd}" ]]
	else
		command -v "${cmd}" >/dev/null 2>&1
	fi
}

pip_cache_supported() {
	local python_bin="$1"

	command_exists "${python_bin}" || return 1
	"${python_bin}" -m pip cache --help >/dev/null 2>&1
}

run_step() {
	local description="$1"
	shift
	local first="${1:-}"

	if [[ -z "${first}" ]]; then
		warn "${description}: missing command"
		return 0
	fi

	if ! command_exists "${first}"; then
		warn "${description}: command not found (${first}) - skipping"
		return 0
	fi

	log "${description}"

	if "$@"; then
		return 0
	else
		local rc=$?
		warn "${description} failed (rc=${rc})"
		overall_rc=1
		return 0
	fi
}

run_root_step() {
	local description="$1"
	shift

	if [[ "${EUID}" -eq 0 ]]; then
		run_step "${description}" "$@"
		return 0
	fi

	if command_exists sudo; then
		run_step "${description}" sudo "$@"
		return 0
	fi

	warn "${description}: root privileges unavailable - skipping"
}

purge_git_state() {
	if ! command_exists git || ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
		warn "Repository cleanup skipped: not inside a git repository"
		return 0
	fi

	run_step "Cleaning ignored Git files" git clean -fdX
}

purge_docker() {
	if ! command_exists docker; then
		warn "Docker not available - skipping docker cleanup"
		return 0
	fi

	run_step "Stopping compose stack and removing volumes" docker compose down --volumes --remove-orphans
	run_step "Pruning Docker system" docker system prune -a --volumes -f
	run_step "Pruning Docker containers" docker container prune -f
	run_step "Pruning Docker images" docker image prune -a -f
	run_step "Pruning Docker volumes" docker volume prune -f
	run_step "Pruning Docker networks" docker network prune -f
	run_step "Pruning Docker builder cache" docker builder prune -a -f

	if docker buildx version >/dev/null 2>&1; then
		run_step "Pruning Docker Buildx cache" docker buildx prune -a -f
	else
		warn "Docker Buildx not available - skipping docker buildx prune"
	fi
}

purge_host_caches() {
	if command_exists journalctl; then
		run_root_step "Vacuuming journald by size" journalctl --vacuum-size=100M
		run_root_step "Vacuuming journald by time" journalctl --vacuum-time=3h
	else
		warn "journalctl not available - skipping journald cleanup"
	fi

	if [[ -n "${PYTHON:-}" ]] && pip_cache_supported "${PYTHON}"; then
		run_step "Purging pip cache" "${PYTHON}" -m pip cache purge
	elif pip_cache_supported python3; then
		run_step "Purging pip cache" python3 -m pip cache purge
	else
		warn "pip cache purge not available - skipping pip cache cleanup"
	fi

	run_step "Clearing npm cache" npm cache clean --force
	run_step "Clearing yarn cache" yarn cache clean
	run_step "Clearing Go module cache" go clean -cache -modcache

	if [[ -f "Cargo.toml" ]]; then
		run_step "Cleaning Cargo build artifacts" cargo clean
	else
		warn "Cargo.toml not found - skipping cargo clean"
	fi

	if command_exists flatpak; then
		run_step "Removing unused Flatpak packages" flatpak uninstall --unused -y
	fi

	if command_exists pacman; then
		run_root_step "Cleaning Arch package cache" pacman -Scc --noconfirm
	fi

	if command_exists apt-get; then
		run_root_step "Cleaning APT cache" apt-get clean
		run_root_step "Autoremoving APT packages" apt-get autoremove --purge -y
	fi

	if command_exists dnf; then
		run_root_step "Cleaning DNF cache" dnf clean all
	fi

	if command_exists yum; then
		run_root_step "Cleaning YUM cache" yum clean all
	fi

	if command_exists brew; then
		run_step "Cleaning Homebrew caches" brew cleanup --prune=all
		run_step "Autoremoving Homebrew packages" brew autoremove
	fi
}

purge_windows() {
	[[ "${INFINITO_IS_WSL2}" == "true" ]] || return 0

	local windows_system32="/mnt/c/Windows/System32"

	if [[ "${PURGE_WINDOWS_CLEANMGR_SETUP:-false}" == "true" ]]; then
		run_step "Configuring Windows Disk Cleanup profile 1" "${windows_system32}/cleanmgr.exe" /sageset:1
	else
		warn "Windows Disk Cleanup profile setup is optional; set PURGE_WINDOWS_CLEANMGR_SETUP=true to run cleanmgr /sageset:1"
	fi

	run_step "Running Windows Disk Cleanup profile 1" "${windows_system32}/cleanmgr.exe" /sagerun:1
	run_step "Running Windows component cleanup" "${windows_system32}/DISM.exe" /Online /Cleanup-Image /StartComponentCleanup
	run_step "Shutting down WSL2" "${windows_system32}/wsl.exe" --shutdown
}

log "Running low-hardware cleanup from ${REPO_ROOT}"

purge_git_state
purge_docker
purge_host_caches
purge_windows

if [[ "${overall_rc}" -eq 0 ]]; then
	log "Cleanup completed successfully"
else
	warn "Cleanup completed with warnings"
fi

exit "${overall_rc}"
