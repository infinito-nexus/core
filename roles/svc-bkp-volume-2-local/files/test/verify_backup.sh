#!/usr/bin/env bash
# Verify the newest backup generation is stored and non-empty (a volume
# counts as payload with a files/ tree or a non-empty sql dump); when
# PREVIOUS_GENERATION is set (async pass) additionally require it to be a
# distinct, newer generation. Requires REPO_DIR/NEWEST_GENERATION from test.sh.
set -euo pipefail

: "${REPO_DIR:?}"
: "${NEWEST_GENERATION:?}"

GEN_DIR="${REPO_DIR}/${NEWEST_GENERATION}"

mapfile -t VOLUME_DIRS < <(find "${GEN_DIR}" -mindepth 2 -maxdepth 2 -type d \( -name files -o -name sql \) -printf '%h\n' | sort -u)
if (( ${#VOLUME_DIRS[@]} < 1 )); then
    echo "FAIL: newest generation ${NEWEST_GENERATION} contains no volume payload"
    exit 1
fi
echo "OK: generation ${NEWEST_GENERATION} stores ${#VOLUME_DIRS[@]} volume(s)"

EMPTY=0
for vol_dir in "${VOLUME_DIRS[@]}"; do
    has_files="$(find "${vol_dir}/files" -mindepth 1 -print -quit 2>/dev/null || true)"
    has_sql="$(find "${vol_dir}/sql" -mindepth 1 -type f -name '*.backup.sql' -size +0 -print -quit 2>/dev/null || true)"
    if [[ -z "${has_files}" ]] && [[ -z "${has_sql}" ]]; then
        echo "WARN: ${vol_dir##*/} backed up empty"
        EMPTY=$((EMPTY + 1))
    fi
done
if (( EMPTY == ${#VOLUME_DIRS[@]} )); then
    echo "FAIL: every backed-up volume in ${NEWEST_GENERATION} is empty"
    exit 1
fi
echo "OK: backup payload present ($(( ${#VOLUME_DIRS[@]} - EMPTY )) non-empty volume(s))"

if [[ -n "${PREVIOUS_GENERATION:-}" ]]; then
    if [[ "${NEWEST_GENERATION}" == "${PREVIOUS_GENERATION}" ]] ||
        [[ "${NEWEST_GENERATION}" < "${PREVIOUS_GENERATION}" ]]; then
        echo "FAIL: newest generation ${NEWEST_GENERATION} is not newer than ${PREVIOUS_GENERATION}"
        exit 1
    fi
    echo "OK: second generation ${NEWEST_GENERATION} stored after ${PREVIOUS_GENERATION}"
fi
