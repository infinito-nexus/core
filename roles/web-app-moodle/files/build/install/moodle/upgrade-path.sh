#!/bin/bash
set -euxo pipefail

: "${MOODLE_SOURCE_DIR:?required}"
: "${MOODLE_VERSION_FILE:?required}"
: "${MOODLE_RELEASE:?required}"
: "${MOODLE_RELEASE_LIB:?required}"
: "${MOODLE_TRANSIT_DIR:?required}"
: "${MOODLE_TRANSIT_RELEASE:?required}"
: "${MOODLE_TRANSIT_TARBALL_URL:?required}"
: "${MOODLE_UPGRADE_PATH:?required}"

# shellcheck source=roles/web-app-moodle/files/build/moodle/release.sh
. "${MOODLE_RELEASE_LIB}"

PINNED="$(moodle_normalize_release "${MOODLE_RELEASE}")"
TRANSIT="$(moodle_normalize_release "${MOODLE_TRANSIT_RELEASE}")"
moodle_release_at_least "${PINNED}" "${TRANSIT}"
[ "${PINNED}" != "${TRANSIT}" ]

PINNED_SHIPPED="$(moodle_release_of "${MOODLE_SOURCE_DIR}/${MOODLE_VERSION_FILE}")"
[ "${PINNED_SHIPPED}" = "${PINNED}" ]
PINNED_REQUIRES="$(moodle_release_requires "${MOODLE_SOURCE_DIR}/$(dirname "${MOODLE_VERSION_FILE}")/admin/environment.xml" "${PINNED}")"

mkdir -p "${MOODLE_TRANSIT_DIR}"
TRANSIT_TARBALL="${MOODLE_TRANSIT_DIR}/${TRANSIT}.tar.gz"
curl --connect-timeout 5 --max-time 600 --retry 3 --retry-all-errors --retry-delay 2 -fSL -o "${TRANSIT_TARBALL}" "${MOODLE_TRANSIT_TARBALL_URL}"

PROBE="$(mktemp -d)"
trap 'rm -rf "${PROBE}"' EXIT
tar -xzf "${TRANSIT_TARBALL}" -C "${PROBE}" --strip-components=1 --wildcards --no-wildcards-match-slash '*/version.php' '*/admin/environment.xml'
TRANSIT_SHIPPED="$(moodle_release_of "${PROBE}/version.php")"
[ "${TRANSIT_SHIPPED}" = "${TRANSIT}" ]
TRANSIT_REQUIRES="$(moodle_release_requires "${PROBE}/admin/environment.xml" "${TRANSIT}")"

printf '%s %s\n' "${TRANSIT}" "${TRANSIT_REQUIRES}" "${PINNED}" "${PINNED_REQUIRES}" > "${MOODLE_UPGRADE_PATH}"
chmod 0644 "${TRANSIT_TARBALL}" "${MOODLE_UPGRADE_PATH}"
