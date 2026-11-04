#!/usr/bin/env bash
# shellcheck shell=bash
# shellcheck disable=SC2016
#
# The mirror belongs here and not in the README template the site publishes:
# the replay exists to prove the instructions a reader copies, and a reader has
# no GHCR mirror to pull from.
#
# Args:
#   $1  the extracted production block, rewritten in place
#
# Env (test.env):
#   GITHUB_REPOSITORY        mirror coordinates; both are empty outside CI, and
#   GITHUB_REPOSITORY_OWNER  the replay then pulls from the upstream registries
#                            the published block names
#   DOCS_TEST_SRC_DIR        checkout whose default.env declares the mirror path

set -euo pipefail

BLOCK="${1:?}"
PREFIX="$(sed -n 's#^INFINITO_GHCR_MIRROR_PREFIX=##p' "${DOCS_TEST_SRC_DIR:?}/default.env")"
OWNER="${GITHUB_REPOSITORY_OWNER:-}"
REPOSITORY="${GITHUB_REPOSITORY:-}"
REPOSITORY="${REPOSITORY##*/}"
PROVISION="infinito administration inventory provision"
MIRRORS='"$INVENTORY/mirrors.yml"'

if [ -z "${PREFIX}" ] || [ -z "${OWNER}" ] || [ -z "${REPOSITORY}" ]; then
	exit 0
fi

if ! grep -q "${PROVISION}" "${BLOCK}"; then
	echo "the block runs no '${PROVISION}', so the mirror has nothing to attach to" >&2
	exit 1
fi

if grep -qE '^docker run ' "${BLOCK}"; then
	ROOT='"$INFINITO_SRC_DIR"'
else
	ROOT='"$PWD"'
fi

RESOLVE="mkdir -p \"\$INVENTORY\" && ( cd ${ROOT} && python3 -m cli.contributing.mirror.resolver"
RESOLVE="${RESOLVE} --repo-root ${ROOT} --ghcr-namespace ${OWNER} --ghcr-repository ${REPOSITORY}"
RESOLVE="${RESOLVE} --ghcr-prefix ${PREFIX} ) > ${MIRRORS} &&"

echo "=== Pulling through the ${OWNER}/${REPOSITORY} GHCR mirror ==="
sed -i "s#${PROVISION} #${PROVISION} --mirror ${MIRRORS} #" "${BLOCK}"
sed -i "/${PROVISION}/i ${RESOLVE}" "${BLOCK}"
