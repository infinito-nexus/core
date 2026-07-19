#!/usr/bin/env bash
set -euo pipefail

KEYRING_DIR="/etc/apt/keyrings"
LEGACY_KEY_PATH="${KEYRING_DIR}/docker.gpg"
KEY_PATH="${KEYRING_DIR}/docker.asc"

usage() {
  cat >&2 <<'EOF'
Usage:
  apt_repo.sh install-key <distro-id>
  apt_repo.sh sanitize-sources <distro-id> [keep-canonical: 0|1] [keyring-path]
  apt_repo.sh ensure-key-and-sanitize <distro-id> [keep-canonical: 0|1] [keyring-path]

Legacy (still accepted):
  apt_repo.sh <distro-id> [keep-canonical: 0|1] [keyring-path]
EOF
}

run_privileged() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    echo "[ERROR] Root privileges are required (sudo unavailable)." >&2
    exit 1
  fi
}

download_file() {
  local url="$1"
  local dest="$2"

  if command -v curl >/dev/null 2>&1; then
    curl --connect-timeout 5 --retry 3 --max-time 120 -fsSL "${url}" -o "${dest}"
    return
  fi

  if command -v wget >/dev/null 2>&1; then
    wget -qO "${dest}" "${url}"
    return
  fi

  if command -v python3 >/dev/null 2>&1; then
    python3 - "${url}" "${dest}" <<'PY'
import pathlib
import sys
import urllib.request

url = sys.argv[1]
dest = pathlib.Path(sys.argv[2])
with urllib.request.urlopen(url) as response:
    dest.write_bytes(response.read())
PY
    return
  fi

  echo "[ERROR] No downloader found (need curl, wget, or python3)." >&2
  exit 1
}

install_key() {
  local distro_id="$1"
  local changed=0
  local tmp=""

  if [[ ! -d "${KEYRING_DIR}" ]]; then
    changed=1
  elif [[ "$(stat -c '%a' "${KEYRING_DIR}" 2>/dev/null || true)" != "755" ]]; then
    changed=1
  fi
  run_privileged install -m 0755 -d "${KEYRING_DIR}"

  if [[ -e "${LEGACY_KEY_PATH}" ]]; then
    run_privileged rm -f "${LEGACY_KEY_PATH}"
    changed=1
  fi

  tmp="$(mktemp)"
  trap 'rm -f "${tmp:-}"' EXIT
  if ! download_file "https://download.docker.com/linux/${distro_id}/gpg" "${tmp}" || [[ ! -s "${tmp}" ]]; then
    echo "[ERROR] Failed to download the Docker GPG key from https://download.docker.com/linux/${distro_id}/gpg." >&2
    return 1
  fi

  if [[ ! -f "${KEY_PATH}" ]] || ! cmp -s "${tmp}" "${KEY_PATH}"; then
    run_privileged install -m 0644 "${tmp}" "${KEY_PATH}"
    changed=1
  elif [[ "$(stat -c '%a' "${KEY_PATH}" 2>/dev/null || true)" != "644" ]]; then
    run_privileged chmod 0644 "${KEY_PATH}"
    changed=1
  fi

  echo "changed=${changed}"
}

sanitize_sources() {
  local distro_id="$1"
  local keep_canonical="${2:-1}"
  local expected_keyring="${3:-/etc/apt/keyrings/docker.asc}"
  local changed=0
  local docker_repo="download.docker.com/linux/${distro_id}"
  local had_nullglob=0
  local file=""
  local tmp=""

  if [[ "${keep_canonical}" != "0" && "${keep_canonical}" != "1" ]]; then
    usage
    exit 2
  fi

  if [[ "${keep_canonical}" -eq 1 && ! -r "${expected_keyring}" ]]; then
    keep_canonical=0
  fi

  if shopt -q nullglob; then
    had_nullglob=1
  else
    shopt -s nullglob
  fi

  for file in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do
    [[ -f "${file}" ]] || continue

    tmp="$(mktemp)"
    awk -v repo="${docker_repo}" -v keyring="${expected_keyring}" -v keep="${keep_canonical}" '
      BEGIN {
        keyring_l = tolower(keyring)
      }
      index($0, repo) > 0 {
        if (keep == "1" && index(tolower($0), keyring_l) > 0) {
          print
        }
        next
      }
      {
        print
      }
    ' "${file}" > "${tmp}"

    if ! cmp -s "${file}" "${tmp}"; then
      mode="$(stat -c '%a' "${file}" 2>/dev/null || echo 644)"
      run_privileged install -m "${mode}" "${tmp}" "${file}"
      changed=1
    fi

    rm -f "${tmp}"

    if [[ "${file}" == /etc/apt/sources.list.d/* ]] && [[ ! -s "${file}" ]]; then
      run_privileged rm -f "${file}"
      changed=1
    fi
  done

  for file in /etc/apt/sources.list.d/*.sources; do
    [[ -f "${file}" ]] || continue
    if grep -Fqi "${docker_repo}" "${file}"; then
      run_privileged rm -f "${file}"
      changed=1
    fi
  done

  if [[ "${had_nullglob}" -eq 0 ]]; then
    shopt -u nullglob
  fi

  echo "changed=${changed}"
}

ensure_key_and_sanitize() {
  local distro_id="$1"
  local keep_canonical="${2:-1}"
  local expected_keyring="${3:-/etc/apt/keyrings/docker.asc}"
  local changed=0
  local output=""

  output="$(install_key "${distro_id}")"
  if [[ "${output}" == *"changed=1"* ]]; then
    changed=1
  fi

  output="$(sanitize_sources "${distro_id}" "${keep_canonical}" "${expected_keyring}")"
  if [[ "${output}" == *"changed=1"* ]]; then
    changed=1
  fi

  echo "changed=${changed}"
}

ACTION="${1:-}"

case "${ACTION}" in
  install-key)
    DISTRO_ID="${2:-}"
    if [[ -z "${DISTRO_ID}" ]]; then
      usage
      exit 2
    fi
    install_key "${DISTRO_ID}"
    ;;
  sanitize-sources)
    DISTRO_ID="${2:-}"
    if [[ -z "${DISTRO_ID}" ]]; then
      usage
      exit 2
    fi
    sanitize_sources "${DISTRO_ID}" "${3:-1}" "${4:-${KEY_PATH}}"
    ;;
  ensure-key-and-sanitize)
    DISTRO_ID="${2:-}"
    if [[ -z "${DISTRO_ID}" ]]; then
      usage
      exit 2
    fi
    ensure_key_and_sanitize "${DISTRO_ID}" "${3:-1}" "${4:-${KEY_PATH}}"
    ;;
  "")
    usage
    exit 2
    ;;
  *)
    sanitize_sources "${1}" "${2:-1}" "${3:-${KEY_PATH}}"
    ;;
esac
