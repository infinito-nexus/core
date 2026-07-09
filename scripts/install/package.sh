#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=/dev/null
source <(grep -E '^INFINITO_DOCKER_CLI_INSTALL_SCRIPT=' "${REPO_ROOT}/default.env")
DOCKER_CLI_INSTALLER="${REPO_ROOT}/${INFINITO_DOCKER_CLI_INSTALL_SCRIPT:?}"

bootstrap_docker_repo() {
	if [[ ! -f "${DOCKER_CLI_INSTALLER}" ]]; then
		echo "[pkg] ERROR: missing docker CLI installer helper at ${DOCKER_CLI_INSTALLER}" >&2
		exit 1
	fi

	echo "[pkg] Bootstrapping Docker package repository metadata..."
	bash "${DOCKER_CLI_INSTALLER}" --repo-only
}

build_and_install_arch() {
	local build_root="/tmp/infinito-nexus-arch-build"
	local pkg_dir="${build_root}/packaging/arch"
	local builder="pkgbuild"
	local pkg_path=""

	echo "[arch] Initializing pacman keyring..."
	pacman-key --init
	pacman-key --populate archlinux
	pacman-key --populate manjaro 2>/dev/null || true

	echo "[arch] Installing build toolchain..."
	pacman -Syu --noconfirm --needed base-devel sudo rsync

	if ! id "${builder}" >/dev/null 2>&1; then
		echo "[arch] Creating build user '${builder}'..."
		useradd -m -s /bin/bash "${builder}"
	fi

	install -d -m 0755 /etc/sudoers.d
	printf '%s ALL=(ALL) NOPASSWD: /usr/bin/pacman\n' "${builder}" >/etc/sudoers.d/99-"${builder}"-pacman
	chmod 0440 /etc/sudoers.d/99-"${builder}"-pacman

	echo "[arch] Preparing build workspace ${build_root}..."
	rm -rf "${build_root}"
	mkdir -p "${build_root}"
	rsync -a --delete \
		--exclude '.git' \
		--exclude '.venv' \
		--exclude '__pycache__' \
		"${REPO_ROOT}/" "${build_root}/"

	chown -R "${builder}:${builder}" "${build_root}"

	echo "[arch] Building package via makepkg..."
	su "${builder}" -c "cd '${pkg_dir}' && makepkg --syncdeps --noconfirm --cleanbuild"

	pkg_path="$(find "${pkg_dir}" -maxdepth 1 -type f -name 'infinito-nexus-*.pkg.tar.*' | head -n1)"
	if [[ -z "${pkg_path}" ]]; then
		echo "[arch] ERROR: built package not found" >&2
		exit 1
	fi

	echo "[arch] Installing ${pkg_path}..."
	pacman -U --noconfirm "${pkg_path}"
}

build_and_install_debian_like() {
	local build_root="/tmp/infinito-nexus-debian-build"
	local deb_path=""

	export DEBIAN_FRONTEND=noninteractive

	if [[ -n "${PACKAGE_INSTALL_FROM:-}" ]]; then
		echo "[debian] Installing pre-built ${PACKAGE_INSTALL_FROM}..."
		apt-get update
		bootstrap_docker_repo
		dpkg -i "${PACKAGE_INSTALL_FROM}" || true
		apt-get install -f -y
		rm -rf /var/lib/apt/lists/*
		return 0
	fi

	echo "[debian] Installing build toolchain..."
	apt-get update
	apt-get install -y --no-install-recommends \
		build-essential \
		debhelper \
		dpkg-dev \
		rsync

	echo "[debian] Preparing build workspace ${build_root}..."
	rm -rf "${build_root}"
	mkdir -p "${build_root}"
	rsync -a \
		--exclude 'packaging/debian' \
		--exclude '.git' \
		"${REPO_ROOT}/" "${build_root}/"
	mkdir -p "${build_root}/debian"
	cp -a "${REPO_ROOT}/packaging/debian/." "${build_root}/debian/"

	echo "[debian] Building package via dpkg-buildpackage..."
	(
		cd "${build_root}"
		dpkg-buildpackage -us -uc -b
	)

	deb_path="$(find /tmp -maxdepth 1 -type f -name 'infinito-nexus_*.deb' | head -n1)"
	if [[ -z "${deb_path}" ]]; then
		echo "[debian] ERROR: built package not found" >&2
		exit 1
	fi

	if [[ "${PACKAGE_BUILD_ONLY:-0}" == "1" ]]; then
		echo "${deb_path}"
		return 0
	fi

	echo "[debian] Installing ${deb_path}..."
	bootstrap_docker_repo
	apt-get install -y "${deb_path}"
	rm -rf /var/lib/apt/lists/*
}

build_and_install_rpm_like() {
	local pm="$1"
	local build_root="/tmp/infinito-nexus-fedora-build"
	local topdir="${build_root}/rpmbuild"
	local rpm_path=""

	echo "[rpm] Installing build toolchain via ${pm}..."
	"${pm}" -y install rpm-build rsync

	echo "[rpm] Preparing rpmbuild tree in ${topdir}..."
	rm -rf "${build_root}"
	mkdir -p "${topdir}"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
	cp "${REPO_ROOT}/packaging/fedora/infinito-nexus.spec" "${topdir}/SPECS/"

	echo "[rpm] Building package via rpmbuild..."
	rpmbuild \
		--define "_topdir ${topdir}" \
		-bb "${topdir}/SPECS/infinito-nexus.spec"

	rpm_path="$(find "${topdir}/RPMS" -type f -name 'infinito-nexus-*.rpm' | head -n1)"
	if [[ -z "${rpm_path}" ]]; then
		echo "[rpm] ERROR: built package not found" >&2
		exit 1
	fi

	echo "[rpm] Installing ${rpm_path} via ${pm}..."
	bootstrap_docker_repo
	"${pm}" -y install "${rpm_path}"
	"${pm}" -y clean all || true
}

main() {
	if command -v pacman >/dev/null 2>&1; then
		build_and_install_arch
	elif command -v apt-get >/dev/null 2>&1; then
		build_and_install_debian_like
	elif command -v dnf >/dev/null 2>&1; then
		build_and_install_rpm_like dnf
	elif command -v yum >/dev/null 2>&1; then
		build_and_install_rpm_like yum
	else
		echo "Unsupported package manager for package build/install" >&2
		exit 1
	fi
}

main "$@"
