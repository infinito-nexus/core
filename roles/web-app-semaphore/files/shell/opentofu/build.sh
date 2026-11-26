#!/usr/bin/env bash
# Args:
#   install <archive> <sha256> <binary>  verify a pinned .tar.gz or .AppImage release, install its file named like <binary> as <binary>
#   runtime                              install the libraries the KeePassXC AppImage takes from the distribution
#   mirror <opentofu-dir> <platform>     mirror every provider each root locks for <platform> into the mirror tofurc names
#   validate <opentofu-dir>              init every root offline from that mirror and validate it once per DNS flavor
#   lock <opentofu-dir> <root> <platform>...  rewrite the lock file of <root> for every platform
set -euo pipefail

readonly FLAVORS=(knot route53 cloudflare)
readonly STAND_IN_WORKSPACE="ws-00000000-0000-4000-8000-000000000000"
readonly STAND_IN_BROKER="http://broker.invalid/client/v4" # nocheck: url
readonly KEEPASSXC_DNF=("libEGL.so.1()(64bit)" "libGLX.so.0()(64bit)" "libOpenGL.so.0()(64bit)"
  "libX11.so.6()(64bit)" "libfontconfig.so.1()(64bit)" "libfreetype.so.6()(64bit)"
  "libharfbuzz.so.0()(64bit)" "libgpg-error.so.0()(64bit)" "libusb-1.0.so.0()(64bit)"
  "libcrypto.so.3()(64bit)" "libz.so.1()(64bit)")
readonly KEEPASSXC_APT=(libegl1 libglx0 libopengl0 libx11-6 libfontconfig1 libfreetype6
  libharfbuzz0b libgpg-error0 libusb-1.0-0 libssl3t64 zlib1g)
readonly KEEPASSXC_PACMAN=(libglvnd libx11 fontconfig freetype2 harfbuzz libgpg-error libusb openssl-3 zlib)

mirror_path() {
  local path
  path="$(sed -nE 's/^[[:space:]]*path[[:space:]]*=[[:space:]]*"([^"]+)"[[:space:]]*$/\1/p' "$1/tofurc")"
  if [[ -z "${path}" || "${path}" == *$'\n'* ]]; then
    echo "build.sh: $1/tofurc names no single mirror path" >&2
    return 1
  fi
  printf '%s\n' "${path}"
}

roots() {
  local root
  for root in "$1"/roots/*/ "$1/records/" "$1/zone/"; do
    printf '%s\n' "${root%/}"
  done
}

stage() {
  local opentofu="$1" root="$2" flavor="$3" target="$4" zone_id=""
  [[ "${flavor}" == "knot" ]] || zone_id="Z0STANDIN"
  cp -a "${root}/." "${target}/"
  rm -rf "${target}/.terraform" "${target}/catalog.json" "${target}/workspace.json"
  mkdir -p "${target}/modules"
  cp -a "${opentofu}/modules/dns-${flavor}" "${target}/modules/dns"
  printf '{"workspace":"%s","dns":{"zone":"example.org","zone_id":"%s"}}\n' \
    "${STAND_IN_WORKSPACE}" "${zone_id}" >"${target}/workspace.json"
  printf '{}\n' >"${target}/catalog.json"
  printf '{"base_url":"%s"}\n' "${STAND_IN_BROKER}" >"${target}/modules/dns/broker.json"
}

each_root_and_flavor() {
  local opentofu="$1" action="$2" root flavor scratch
  while IFS= read -r root; do
    for flavor in "${FLAVORS[@]}"; do
      scratch="$(mktemp -d)"
      stage "${opentofu}" "${root}" "${flavor}" "${scratch}"
      "${action}" "${scratch}" "${root##*/}" "${flavor}"
      rm -rf "${scratch}"
    done
  done < <(roots "${opentofu}")
}

install_member() {
  local archive="$1" scratch="$2" binary="$3" member
  tar -xzf "${archive}" -C "${scratch}"
  member="$(find "${scratch}" -type f -name "${binary##*/}")"
  if [[ -z "${member}" || "${member}" == *$'\n'* ]]; then
    echo "build.sh: ${archive} holds no single ${binary##*/}" >&2
    return 1
  fi
  install -m 0755 "${member}" "${binary}"
}

install_appimage() {
  local archive="$1" scratch="$2" binary="$3" appdir
  appdir="${binary%/*/*}/lib/${binary##*/}"
  install -m 0700 "${archive}" "${scratch}/release.AppImage"
  (cd "${scratch}" && ./release.AppImage --appimage-extract >/dev/null)
  test -x "${scratch}/squashfs-root/usr/bin/${binary##*/}"
  mkdir -p "${appdir%/*}"
  mv "${scratch}/squashfs-root" "${appdir}"
  ln -s "${appdir}/usr/bin/${binary##*/}" "${binary}"
}

install_release() {
  local archive="$1" sum="$2" binary="$3" scratch
  if [[ ! "${sum}" =~ ^[0-9a-f]{64}$ ]]; then
    echo "build.sh: the pinned sum '${sum}' of ${archive} is no sha256" >&2
    return 1
  fi
  printf '%s  %s\n' "${sum}" "${archive}" | sha256sum --check --strict --quiet -
  scratch="$(mktemp -d)"
  case "${archive}" in
    *.tar.gz) install_member "${archive}" "${scratch}" "${binary}" ;;
    *.AppImage) install_appimage "${archive}" "${scratch}" "${binary}" ;;
    *)
      echo "build.sh: ${archive} is no .tar.gz or .AppImage" >&2
      return 1
      ;;
  esac
  rm -rf "${scratch}"
  "${binary}" --version
}

install_runtime() {
  if command -v dnf >/dev/null 2>&1; then
    dnf -y install --setopt=install_weak_deps=False "${KEEPASSXC_DNF[@]}"
    dnf clean all
  elif command -v apt-get >/dev/null 2>&1; then
    apt-get -o Acquire::Retries=3 update
    DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y --no-install-recommends "${KEEPASSXC_APT[@]}"
    rm -rf /var/lib/apt/lists/*
  elif command -v pacman >/dev/null 2>&1; then
    pacman -Syu --noconfirm --needed "${KEEPASSXC_PACMAN[@]}"
  else
    echo "build.sh: runtime needs dnf, apt-get or pacman" >&2
    return 1
  fi
}

install_modules() {
  env -u TF_CLI_CONFIG_FILE tofu -chdir="$1" get
}

mirror_one() {
  install_modules "$1"
  env -u TF_CLI_CONFIG_FILE tofu -chdir="$1" providers mirror -platform="${PLATFORM}" "${MIRROR}"
}

lock_root() {
  local opentofu="$1" root="$2" scratch platform
  local -a platforms=()
  shift 2
  for platform in "$@"; do
    platforms+=("-platform=${platform}")
  done
  scratch="$(mktemp -d)"
  stage "${opentofu}" "${root}" "${FLAVORS[0]}" "${scratch}"
  install_modules "${scratch}"
  env -u TF_CLI_CONFIG_FILE tofu -chdir="${scratch}" providers lock "${platforms[@]}"
  cp "${scratch}/.terraform.lock.hcl" "${root}/.terraform.lock.hcl"
  rm -rf "${scratch}"
}

validate_one() {
  tofu -chdir="$1" init -backend=false -lockfile=readonly -input=false -no-color
  tofu -chdir="$1" validate -no-color
  printf 'validated %s with %s\n' "$2" "$3"
}

main() {
  local command="${1:-}"
  case "${command}" in
    install)
      [[ $# -eq 4 ]] || { echo "build.sh: install <archive> <sha256> <binary>" >&2; return 2; }
      install_release "$2" "$3" "$4"
      ;;
    runtime)
      [[ $# -eq 1 ]] || { echo "build.sh: runtime" >&2; return 2; }
      install_runtime
      ;;
    mirror)
      [[ $# -eq 3 ]] || { echo "build.sh: mirror <opentofu-dir> <platform>" >&2; return 2; }
      if [[ ! "$3" =~ ^linux_[a-z0-9]+$ ]]; then
        echo "build.sh: mirror platform '$3' is no linux_<architecture>" >&2
        return 2
      fi
      PLATFORM="$3"
      MIRROR="$(mirror_path "$2")"
      mkdir -p "${MIRROR}"
      each_root_and_flavor "$2" mirror_one
      ;;
    validate)
      [[ $# -eq 2 ]] || { echo "build.sh: validate <opentofu-dir>" >&2; return 2; }
      mirror_path "$2" >/dev/null
      export TF_CLI_CONFIG_FILE="$2/tofurc" TF_IN_AUTOMATION=1 TF_INPUT=0
      each_root_and_flavor "$2" validate_one
      ;;
    lock)
      [[ $# -ge 4 ]] || { echo "build.sh: lock <opentofu-dir> <root> <platform>..." >&2; return 2; }
      lock_root "${@:2}"
      ;;
    *)
      echo "build.sh: install, runtime, mirror, validate or lock" >&2
      return 2
      ;;
  esac
}

main "$@"
