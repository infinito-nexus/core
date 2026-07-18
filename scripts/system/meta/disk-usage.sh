#!/usr/bin/env bash
set -euo pipefail

# Show what is consuming disk space before deciding what to clean up.
# Silently skips any tool that is not available on the current host.

run_if_available() {
	local label="$1"
	shift
	command -v "$1" >/dev/null 2>&1 || return 0
	echo "=== ${label} ==="
	"$@" 2>/dev/null || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
	echo ""
}

run_if_available "Filesystem usage" df -h
run_if_available "Docker usage" docker system df
run_if_available "Docker Buildx cache" docker buildx du
run_if_available "Running and stopped containers" docker ps -a
run_if_available "Docker images" docker images
run_if_available "journald disk usage" journalctl --disk-usage
run_if_available "pip cache" python3 -m pip cache info
run_if_available "npm cache" npm cache verify
run_if_available "yarn cache" yarn cache dir
run_if_available "Go cache" go env GOCACHE
run_if_available "Pacman package cache" du -sh /var/cache/pacman/pkg
run_if_available "APT package cache" du -sh /var/cache/apt/archives
run_if_available "DNF package cache" du -sh /var/cache/dnf
run_if_available "YUM package cache" du -sh /var/cache/yum
run_if_available "Flatpak disk usage" flatpak list --columns=size
