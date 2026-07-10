#!/usr/bin/env bash
# Replay the text dumps of the backup generation into the running
# databases via baudolo-restore postgres|mariadb --empty. Requires the
# containers restarted by restore_cycle.sh and credentials from
# databases.csv (semicolon-separated: instance;database;username;password).
# Cluster dumps (<instance>.cluster.backup.sql, database='*') are skipped
# visibly: baudolo-restore has no cluster replay path.
set -euo pipefail

: "${BKP_TEST_BACKUPS_DIR:?}"
: "${BKP_TEST_DATABASES_CSV:?}"
: "${BKP_TEST_RESTORE_BIN:?}"
: "${MACHINE_HASH:?}"
: "${REPO_DIR:?}"
: "${REPO_NAME:?}"
: "${NEWEST_GENERATION:?}"

GEN_DIR="${REPO_DIR}/${NEWEST_GENERATION}"

if [[ ! -f "${BKP_TEST_DATABASES_CSV}" ]]; then
    echo "FAIL: databases csv missing at ${BKP_TEST_DATABASES_CSV}"
    exit 1
fi

mapfile -t CLUSTER_DUMPS < <(find "${GEN_DIR}" -mindepth 3 -maxdepth 3 -type f -path '*/sql/*.cluster.backup.sql' | sort)
for cluster_dump in "${CLUSTER_DUMPS[@]}"; do
    echo "SKIP: cluster dump ${cluster_dump##*/} (database='*') has no single-db replay path"
done

mapfile -t SQL_FILES < <(find "${GEN_DIR}" -mindepth 3 -maxdepth 3 -type f -path '*/sql/*.backup.sql' ! -name '*.cluster.backup.sql' | sort)
if (( ${#SQL_FILES[@]} < 1 )); then
    echo "OK: generation ${NEWEST_GENERATION} carries no single-db sql dumps; nothing to replay"
    exit 0
fi
echo "Replaying ${#SQL_FILES[@]} sql dump(s) from generation ${NEWEST_GENERATION}"

RESTORED=0
for sql_file in "${SQL_FILES[@]}"; do
    volume="$(basename "$(dirname "$(dirname "${sql_file}")")")"
    db_name="$(basename "${sql_file}" .backup.sql)"

    row="$(awk -F';' -v db="${db_name}" 'NR > 1 && $2 == db { print; exit }' "${BKP_TEST_DATABASES_CSV}")"
    if [[ -z "${row}" ]]; then
        echo "SKIP: no databases.csv row for '${db_name}' (volume ${volume})"
        continue
    fi
    IFS=';' read -r _instance _database db_user db_password <<<"${row}"

    container="$(container ps --filter "volume=${volume}" --format '{{.Names}}' | head -n1)"
    if [[ -z "${container}" ]]; then
        echo "SKIP: no running container mounts volume ${volume}"
        continue
    fi

    image="$(container inspect -f '{{.Config.Image}}' "${container}")"
    case "${image}" in
        *postgres*) engine="postgres" ;;
        *mariadb* | *mysql*) engine="mariadb" ;;
        *)
            echo "SKIP: cannot derive db engine from image '${image}' (container ${container})"
            continue
            ;;
    esac

    "${BKP_TEST_RESTORE_BIN}" "${engine}" "${volume}" "${MACHINE_HASH}" "${NEWEST_GENERATION}" \
        --backups-dir "${BKP_TEST_BACKUPS_DIR}" \
        --repo-name "${REPO_NAME}" \
        --container "${container}" \
        --db-name "${db_name}" \
        --db-user "${db_user}" \
        --db-password "${db_password}" \
        --empty
    echo "OK: replayed ${engine} dump '${db_name}' into ${container}"
    RESTORED=$((RESTORED + 1))
done

if (( RESTORED < 1 )); then
    echo "FAIL: sql dumps present but none could be replayed"
    exit 1
fi
echo "OK: ${RESTORED} database dump(s) replayed"
