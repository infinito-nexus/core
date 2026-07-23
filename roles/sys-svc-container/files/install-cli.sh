#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
. /etc/os-release

REPO_ONLY=0
if [[ "${1:-}" == "--repo-only" ]]; then
  REPO_ONLY=1
  shift
fi

echo ">>> Installing docker client on ID=${ID} ID_LIKE=${ID_LIKE:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_APT_SANITIZER="${SCRIPT_DIR}/apt_repo.sh"

sanitize_docker_apt_sources() {
  local distro_id="$1"
  local keep_canonical="${2:-1}"

  bash "${DOCKER_APT_SANITIZER}" sanitize-sources "${distro_id}" "${keep_canonical}" >/dev/null
}

ensure_docker_apt_key_and_sources() {
  local distro_id="$1"
  local keep_canonical="${2:-1}"

  bash "${DOCKER_APT_SANITIZER}" ensure-key-and-sanitize "${distro_id}" "${keep_canonical}" >/dev/null
}

add_repo_rpm_compatible() {
  local pm="$1"
  local repo_url="$2"
  local repo_file
  repo_file="/etc/yum.repos.d/$(basename "${repo_url}")"

  if [[ -s "${repo_file}" ]]; then
    return 0
  fi

  # dnf4/yum: `config-manager --add-repo URL`
  if "${pm}" config-manager --add-repo "${repo_url}" >/dev/null 2>&1; then
    return 0
  fi

  # dnf5: `config-manager addrepo --from-repofile=URL`
  if "${pm}" config-manager addrepo --from-repofile="${repo_url}" >/dev/null 2>&1; then
    return 0
  fi

  echo "[ERROR] Failed to add repo ${repo_url} via ${pm} config-manager" >&2
  return 1
}

# shellcheck disable=SC2031
if [[ "${ID}" == "arch" || "${ID_LIKE:-}" =~ arch ]]; then
  if [[ "${REPO_ONLY}" != "1" ]]; then
    pacman-key --init
    pacman -Syu --noconfirm --needed docker
  fi

elif [[ "${ID}" == "debian" || "${ID}" == "ubuntu" || "${ID_LIKE:-}" =~ debian ]]; then
  export DEBIAN_FRONTEND=noninteractive
  sanitize_docker_apt_sources "${ID}" 0

  # Ubuntu 26.04 ships docker-compose-v2 in universe with no Conflicts:
  # against Docker upstream's docker-compose-plugin; both place a binary
  # at /usr/libexec/docker/cli-plugins/docker-compose and dpkg aborts
  # if a later transaction pulls docker-compose-v2 as a recommended
  # dep (e.g. via ansible). Pin it out of selection on Ubuntu only.
  # TODO: drop this once Ubuntu adds the Conflicts: marker.
  # Tracking: https://bugs.launchpad.net/ubuntu/+source/docker-compose-v2/+bug/2151249
  if [[ "${ID}" == "ubuntu" ]]; then
    mkdir -p /etc/apt/preferences.d
    cat >/etc/apt/preferences.d/00-block-ubuntu-docker-compose-v2 <<'EOF'
Package: docker-compose-v2
Pin: release o=Ubuntu
Pin-Priority: -1
EOF
    apt-get -y purge docker-compose-v2 >/dev/null 2>&1 || true
  fi

  apt-get update
  apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    lsb-release
  ensure_docker_apt_key_and_sources "${ID}" 1

  # shellcheck disable=SC1091
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${ID} $(. /etc/os-release && echo "${VERSION_CODENAME}") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  if [[ "${REPO_ONLY}" != "1" ]]; then
    apt-get install -y --no-install-recommends \
      docker-buildx-plugin \
      docker-ce-cli \
      docker-compose-plugin
  fi

elif [[ "${ID}" == "fedora" ]]; then
  dnf -y install dnf-plugins-core
  add_repo_rpm_compatible dnf "https://download.docker.com/linux/fedora/docker-ce.repo"
  if [[ "${REPO_ONLY}" == "1" ]]; then
    dnf -y makecache
  else
    dnf -y install --allowerasing docker-ce-cli docker-buildx-plugin docker-compose-plugin
  fi

elif [[ "${ID}" == "centos" || "${ID}" == "rhel" || "${ID_LIKE:-}" =~ (rhel|centos) ]]; then
  if command -v dnf >/dev/null 2>&1; then PM=dnf; else PM=yum; fi
  ${PM} -y install yum-utils || true
  ${PM} -y install dnf-plugins-core || true
  add_repo_rpm_compatible "${PM}" "https://download.docker.com/linux/centos/docker-ce.repo" || true
  if [[ "${REPO_ONLY}" == "1" ]]; then
    ${PM} -y makecache || true
  else
    # Prefer the same Docker CLI/buildx/compose package set as Fedora.
    (${PM} -y install docker-ce-cli docker-buildx-plugin docker-compose-plugin) || \
      (${PM} -y install docker-ce-cli) || \
      (${PM} -y install docker) || true
  fi

else
  echo "[ERROR] Unsupported distro for docker client install: ID=${ID} ID_LIKE=${ID_LIKE:-}" >&2
  exit 1
fi
