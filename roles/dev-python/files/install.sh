#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-ensure}"
case "${MODE}" in
  ensure | print) ;;
  *)
    echo "Usage: $0 [ensure|print]" >&2
    exit 2
    ;;
esac

if [[ "${MODE}" == "print" ]]; then
  exec 3>&1
  exec 1>&2
fi

if [[ ! -f /etc/os-release ]]; then
  echo "[ERROR] /etc/os-release not found; unsupported system." >&2
  exit 1
fi

# shellcheck disable=SC1091
. /etc/os-release
ID_LIKE="${ID_LIKE:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
DOCKER_APT_SANITIZER="${REPO_ROOT}/roles/sys-svc-container/files/apt_repo.sh"

log() {
  printf '>>> [dev-python] %s\n' "$*"
}

run_privileged() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    return 1
  fi
}

can_run_privileged() {
  if [[ "${EUID}" -eq 0 ]]; then
    return 0
  fi
  command -v sudo >/dev/null 2>&1 || return 1
  sudo -n true >/dev/null 2>&1
}

need_privileged_or_fail() {
  if can_run_privileged; then
    return 0
  fi
  echo "[ERROR] Root privileges are required (sudo unavailable)." >&2
  exit 1
}

sanitize_debian_docker_apt_sources() {
  local distro_id="$1"

  if [[ -v SKIP_DOCKER_APT_SANITIZER && "${SKIP_DOCKER_APT_SANITIZER}" == "1" ]]; then
    return 0
  fi

  run_privileged bash "${DOCKER_APT_SANITIZER}" sanitize-sources "${distro_id}" 1 >/dev/null
}

find_highest_apt_python_pkg() {
  apt-cache pkgnames 2>/dev/null \
    | grep -E '^python3\.[0-9]+$' \
    | sort -V \
    | tail -n1
}

find_highest_rpm_python_pkg() {
  local pm="$1"
  {
    run_privileged "${pm}" -q list installed "python3.[0-9]*" 2>/dev/null || true
    run_privileged "${pm}" -q list --available "python3.[0-9]*" 2>/dev/null || true
  } \
    | awk '/^python3\.[0-9]+\./ {pkg=$1; sub(/\.[^.]+$/, "", pkg); print pkg}' \
    | sort -Vu \
    | tail -n1
}

rpm_pkg_exists() {
  local pm="$1"
  local pkg="$2"

  run_privileged "${pm}" -q list --available "${pkg}" >/dev/null 2>&1 \
    || run_privileged "${pm}" -q list installed "${pkg}" >/dev/null 2>&1
}

install_versioned_rpm_python_and_pip() {
  local pm="$1"
  local py_pkg="$2"
  local pip_pkg="${py_pkg}-pip"

  run_privileged "${pm}" -y install "${py_pkg}" || true
  if rpm_pkg_exists "${pm}" "${pip_pkg}"; then
    run_privileged "${pm}" -y install "${pip_pkg}" || true
  else
    log "Skipping unavailable package ${pip_pkg}; using generic python3-pip fallback if present."
  fi
}

install_python_packages() {
  need_privileged_or_fail

  case "${ID}" in
    arch | manjaro)
      run_privileged pacman-key --init
      run_privileged pacman -Syu --noconfirm --needed python python-pip
      run_privileged pacman -Scc --noconfirm || true
      ;;

    debian | ubuntu)
      local apt_best_pkg=""

      export DEBIAN_FRONTEND=noninteractive
      sanitize_debian_docker_apt_sources "${ID}"
      run_privileged apt-get update
      run_privileged apt-get install -y --no-install-recommends python3 python3-pip
      apt_best_pkg="$(find_highest_apt_python_pkg || true)"
      if [[ "${apt_best_pkg}" =~ ^python3\.([0-9]+)$ ]] && (( BASH_REMATCH[1] >= 11 )); then
        run_privileged apt-get install -y --no-install-recommends "${apt_best_pkg}" || true
        if apt-cache show "${apt_best_pkg}-venv" >/dev/null 2>&1; then
          run_privileged apt-get install -y --no-install-recommends "${apt_best_pkg}-venv" || true
        fi
      fi
      run_privileged rm -rf /var/lib/apt/lists/*
      ;;

    fedora)
      local dnf_best_pkg=""

      run_privileged dnf -y install python3 python3-pip
      dnf_best_pkg="$(find_highest_rpm_python_pkg dnf || true)"
      if [[ "${dnf_best_pkg}" =~ ^python3\.([0-9]+)$ ]] && (( BASH_REMATCH[1] >= 11 )); then
        install_versioned_rpm_python_and_pip dnf "${dnf_best_pkg}"
      fi
      run_privileged dnf -y clean all || true
      run_privileged rm -rf /var/cache/dnf || true
      ;;

    centos | rhel)
      local rpm_best_pkg=""

      if command -v dnf >/dev/null 2>&1; then
        PM=dnf
      else
        PM=yum
      fi
      run_privileged "${PM}" -y install python3 python3-pip || true
      rpm_best_pkg="$(find_highest_rpm_python_pkg "${PM}" || true)"
      if [[ "${rpm_best_pkg}" =~ ^python3\.([0-9]+)$ ]] && (( BASH_REMATCH[1] >= 11 )); then
        install_versioned_rpm_python_and_pip "${PM}" "${rpm_best_pkg}"
      fi
      run_privileged "${PM}" -y clean all || true
      run_privileged rm -rf "/var/cache/${PM}" || true
      ;;

    *)
      local rpm_like_best_pkg=""

      if [[ "${ID_LIKE}" =~ (rhel|centos) ]]; then
        if command -v dnf >/dev/null 2>&1; then
          PM=dnf
        else
          PM=yum
        fi
        run_privileged "${PM}" -y install python3 python3-pip || true
        rpm_like_best_pkg="$(find_highest_rpm_python_pkg "${PM}" || true)"
        if [[ "${rpm_like_best_pkg}" =~ ^python3\.([0-9]+)$ ]] && (( BASH_REMATCH[1] >= 11 )); then
          install_versioned_rpm_python_and_pip "${PM}" "${rpm_like_best_pkg}"
        fi
        run_privileged "${PM}" -y clean all || true
        run_privileged rm -rf "/var/cache/${PM}" || true
      else
        echo "[ERROR] Unsupported distro for Python install: ID=${ID} ID_LIKE=${ID_LIKE}" >&2
        exit 1
      fi
      ;;
  esac
}

python_is_311_or_higher() {
  local bin="$1"
  command -v "${bin}" >/dev/null 2>&1 || return 1
  "${bin}" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
}

python_has_pip_module() {
  local bin="$1"
  command -v "${bin}" >/dev/null 2>&1 || return 1
  "${bin}" -m pip --version >/dev/null 2>&1
}

python_minor_version() {
  local bin="$1"
  "${bin}" - <<'PY' 2>/dev/null
import sys
print(f"{sys.version_info[0]}.{sys.version_info[1]}")
PY
}

canonicalize_python_candidate() {
  local bin="$1"
  local resolved=""

  if resolved="$(readlink -f -- "${bin}" 2>/dev/null)" && [[ -x "${resolved}" ]]; then
    printf '%s\n' "${resolved}"
    return 0
  fi

  printf '%s\n' "${bin}"
}

pick_python_bin() {
  local bin candidate name version
  local best_version="" best_bin=""
  local best_pip_version="" best_pip_bin=""
  for bin in \
    /usr/local/bin/python3.* \
    /usr/bin/python3.* \
    /usr/local/bin/python3 \
    /usr/bin/python3 \
    python3; do
    [[ -x "${bin}" ]] || continue
    candidate="$(canonicalize_python_candidate "${bin}")"
    [[ -x "${candidate}" ]] || continue
    name="$(basename "${candidate}")"
    if [[ "${name}" == python3.* ]] && [[ ! "${name}" =~ ^python3\.[0-9]+$ ]]; then
      continue
    fi
    if ! python_is_311_or_higher "${candidate}"; then
      continue
    fi
    version="$(python_minor_version "${candidate}")"
    [[ -n "${version}" ]] || continue
    if [[ -z "${best_version}" ]] || [[ "$(printf '%s\n%s\n' "${best_version}" "${version}" | sort -V | tail -n1)" == "${version}" ]]; then
      best_version="${version}"
      best_bin="${candidate}"
    fi
    if python_has_pip_module "${candidate}"; then
      if [[ -z "${best_pip_version}" ]] || [[ "$(printf '%s\n%s\n' "${best_pip_version}" "${version}" | sort -V | tail -n1)" == "${version}" ]]; then
        best_pip_version="${version}"
        best_pip_bin="${candidate}"
      fi
    fi
  done
  if [[ -n "${best_pip_bin}" ]]; then
    printf '%s\n' "${best_pip_bin}"
    return 0
  fi
  [[ -n "${best_bin}" ]] || return 1
  printf '%s\n' "${best_bin}"
}

configure_defaults() {
  local pybin="$1"
  local pyver
  local versioned_pip
  local pybin_resolved=""

  need_privileged_or_fail

  if pybin_resolved="$(readlink -f -- "${pybin}" 2>/dev/null)" && [[ -x "${pybin_resolved}" ]]; then
    pybin="${pybin_resolved}"
  fi

  if [[ "${pybin}" == "/usr/local/bin/python3" ]]; then
    echo "[ERROR] Refusing to link /usr/local/bin/python3 to itself." >&2
    exit 1
  fi

  pyver="$("${pybin}" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
  versioned_pip="/usr/bin/pip${pyver}"

  run_privileged install -d /usr/local/bin
  run_privileged ln -sfn "${pybin}" /usr/local/bin/python3
  run_privileged ln -sfn /usr/local/bin/python3 /usr/local/bin/python

  if [[ -x "${versioned_pip}" ]]; then
    run_privileged ln -sfn "${versioned_pip}" /usr/local/bin/pip3
  else
    if ! "${pybin}" -m pip --version >/dev/null 2>&1; then
      run_privileged "${pybin}" -m ensurepip --upgrade >/dev/null 2>&1 || true
    fi
    if "${pybin}" -m pip --version >/dev/null 2>&1; then
      run_privileged tee /usr/local/bin/pip3 >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exec /usr/local/bin/python3 -m pip "$@"
EOF
      run_privileged chmod 0755 /usr/local/bin/pip3
    elif [[ -x /usr/bin/pip3 ]] && /usr/bin/pip3 --version 2>/dev/null | grep -q "python ${pyver}"; then
      run_privileged ln -sfn /usr/bin/pip3 /usr/local/bin/pip3
    else
      echo "[ERROR] Could not provide pip3 for Python ${pyver}." >&2
      exit 1
    fi
  fi

  run_privileged ln -sfn /usr/local/bin/pip3 /usr/local/bin/pip

}

resolve_python_bin_or_fail() {
  if PYBIN="$(pick_python_bin)"; then
    return 0
  fi
  echo "[ERROR] No Python >= 3.11 found after installation attempt." >&2
  if command -v python3 >/dev/null 2>&1; then
    python3 --version || true
  fi
  exit 1
}

ensure_python_bin() {
  log "Ensuring highest available Python >=3.11 for ID=${ID} ID_LIKE=${ID_LIKE}"
  install_python_packages
  hash -r || true
  resolve_python_bin_or_fail
}

resolve_or_install_python_bin() {
  if PYBIN="$(pick_python_bin)"; then
    return 0
  fi
  ensure_python_bin
}

if [[ "${MODE}" == "ensure" ]]; then
  if PYBIN="$(pick_python_bin)"; then
    if ! can_run_privileged; then
      log "Using existing Python without privileged system-wide symlink updates: $("${PYBIN}" --version)"
      if "${PYBIN}" -m pip --version >/dev/null 2>&1; then
        log "Existing pip: $("${PYBIN}" -m pip --version)"
        exit 0
      fi
    fi
  else
    ensure_python_bin
  fi

  configure_defaults "${PYBIN}"
  log "Default python: $(python3 --version)"
  log "Default pip: $(pip3 --version)"
else
  resolve_or_install_python_bin
  printf '%s\n' "${PYBIN}" >&3
fi
