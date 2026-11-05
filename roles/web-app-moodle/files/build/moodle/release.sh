#!/bin/bash

# Param: $1 a Moodle release string such as "4.5.15+ (Build: 20261021)" or "5.3"; prints it as major.minor.patch.
moodle_normalize_release() {
  local release="${1%% *}"
  release="$(printf '%s' "${release}" | tr -c '0-9.' '.' | tr -s '.')"
  release="${release#.}"
  release="${release%.}"
  case "${release}" in
    "") return 1 ;;
    *.*.*) ;;
    *.*) release="${release}.0" ;;
    *) release="${release}.0.0" ;;
  esac
  printf '%s\n' "${release}"
}

# Param: $1 path of a Moodle version.php; prints the normalized $release it declares.
moodle_release_of() {
  local declared
  declared="$(sed -n "s/^[[:space:]]*\$release[[:space:]]*=[[:space:]]*'\([^']*\)'.*/\1/p" "$1" | head -n 1)"
  [ -n "${declared}" ] || return 1
  moodle_normalize_release "${declared}"
}

# Param: $1 release, $2 release, both normalized; succeeds when $1 is $2 or newer.
moodle_release_at_least() {
  [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n 1)" = "$2" ]
}

# Param: $1 path of a Moodle admin/environment.xml, $2 normalized release; prints the oldest release Moodle upgrades to $2 from.
moodle_release_requires() {
  local branch="${2%.*}" requires
  requires="$(grep -o -E "<MOODLE version=\"${branch//./\\.}\" requires=\"[^\"]+\"" "$1" | sed -E 's/.*requires="([^"]+)"/\1/' | head -n 1)"
  [ -n "${requires}" ] || return 1
  moodle_normalize_release "${requires}"
}

# Param: $1 normalized release the site runs, $2 upgrade path file with one "<release> <oldest source>" line per release the image ships; prints the newest of them Moodle upgrades $1 to.
moodle_next_release() {
  local release requires next=""
  while read -r release requires; do
    moodle_release_at_least "$1" "${requires}" || continue
    moodle_release_at_least "$1" "${release}" && continue
    if [ -z "${next}" ] || moodle_release_at_least "${release}" "${next}"; then
      next="${release}"
    fi
  done < "$2"
  [ -n "${next}" ] || return 1
  printf '%s\n' "${next}"
}
