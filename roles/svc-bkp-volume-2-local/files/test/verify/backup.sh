#!/usr/bin/env bash
# Verify the newest backup generation is stored, non-empty, and dumped where a
# dump was owed: a volume counts as payload with a files/ tree or a non-empty
# sql dump, and a volume the run recorded as a database must carry the dump.
# The generation's own manifest is the authority; a generation written before
# baudolo wrote one is judged by the engine's on-disk footprint instead.
# Requires REPO_DIR/NEWEST_GENERATION/BKP_TEST_REPO_ROOT from test.sh.
set -euo pipefail

: "${REPO_DIR:?}"
: "${NEWEST_GENERATION:?}"
: "${BKP_TEST_REPO_ROOT:?}"
: "${BKP_TEST_PYTHON:?}"

GEN_DIR="${REPO_DIR}/${NEWEST_GENERATION}"

mapfile -t VOLUME_DIRS < <(find "${GEN_DIR}" -mindepth 2 -maxdepth 2 -type d \( -name files -o -name sql \) -printf '%h\n' | sort -u)
if (( ${#VOLUME_DIRS[@]} < 1 )); then
    echo "FAIL: newest generation ${NEWEST_GENERATION} contains no volume payload"
    exit 1
fi
echo "OK: generation ${NEWEST_GENERATION} stores ${#VOLUME_DIRS[@]} volume(s)"

DB_ENGINE_MARKERS=(
    "postgres:PG_VERSION"
    "mariadb:ibdata1"
    "mariadb:mysql/user.frm"
    "mariadb:mysql/user.ibd"
)

engine_of() {
    local files_dir="$1" marker
    for marker in "${DB_ENGINE_MARKERS[@]}"; do
        if [[ -e "${files_dir}/${marker#*:}" ]]; then
            echo "${marker%%:*}"
            return 0
        fi
    done
    return 1
}

MANIFEST_LINES=""
if MANIFEST_LINES="$(PYTHONPATH="${BKP_TEST_REPO_ROOT}" "${BKP_TEST_PYTHON}" -m utils.recovery.manifest "${GEN_DIR}")"; then
    FROM_MANIFEST=true
    echo "OK: generation ${NEWEST_GENERATION} carries a manifest; reading its verdict"
else
    FROM_MANIFEST=false
    echo "NOTE: generation ${NEWEST_GENERATION} predates the manifest; judging by the engine footprint"
fi

EMPTY=0
UNDUMPED=()
for vol_dir in "${VOLUME_DIRS[@]}"; do
    has_files="$(find "${vol_dir}/files" -mindepth 1 -print -quit 2>/dev/null || true)"
    has_sql="$(find "${vol_dir}/sql" -mindepth 1 -type f -name '*.backup.sql' -size +0 -print -quit 2>/dev/null || true)"
    if [[ -z "${has_files}" ]] && [[ -z "${has_sql}" ]]; then
        echo "WARN: ${vol_dir##*/} backed up empty"
        EMPTY=$((EMPTY + 1))
        continue
    fi
    if [[ "${FROM_MANIFEST}" == "false" ]] \
        && engine="$(engine_of "${vol_dir}/files")" \
        && [[ -z "${has_sql}" ]]; then
        UNDUMPED+=("${vol_dir##*/} (${engine})")
    fi
done

if [[ "${FROM_MANIFEST}" == "true" ]] && [[ -n "${MANIFEST_LINES}" ]]; then
    while IFS=$'\t' read -r volume engine; do
        if [[ -n "${volume}" ]]; then
            UNDUMPED+=("${volume} (${engine})")
        fi
    done <<< "${MANIFEST_LINES}"
fi
if (( EMPTY == ${#VOLUME_DIRS[@]} )); then
    echo "FAIL: every backed-up volume in ${NEWEST_GENERATION} is empty"
    exit 1
fi
if (( ${#UNDUMPED[@]} > 0 )); then
    echo "FAIL: ${#UNDUMPED[@]} volume(s) hold a live database data directory but no sql dump: ${UNDUMPED[*]}"
    echo "      Usual cause: no row in the databases.csv baudolo reads, so it had no credentials to dump with."
    exit 1
fi
echo "OK: backup payload present ($(( ${#VOLUME_DIRS[@]} - EMPTY )) non-empty volume(s)), every database volume dumped"
