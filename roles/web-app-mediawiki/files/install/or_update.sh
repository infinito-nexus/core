#!/usr/bin/env bash
# Update runs as a one-shot throwaway container, not `container exec` against
# the live task: under swarm a not-yet-installed task can be reaped by the
# healthcheck mid-update otherwise.
set -euo pipefail

NETWORK="$1"; MARIADB_VERSION="$2"
DB_HOST="$3"; DB_PORT="$4"; DB_USER="$5"; DB_NAME="$6"
MW_USER="$7"; MW_IMAGE="$8"; MW_VERSION="$9"; MW_HTML_DIR="${10}"
MW_URL="${11}"; MW_SITENAME="${12}"; ADMIN_NAME="${13}"

{ IFS= read -r MW_DB_PASSWORD && IFS= read -r MW_ADMIN_PASSWORD; } || {
    echo "the database and the admin password must arrive on stdin, one per line" >&2
    exit 1
}
: "${MW_DB_PASSWORD:?the database password must be the first line on stdin}"
: "${MW_ADMIN_PASSWORD:?the admin password must be the second line on stdin}"
export MW_DB_PASSWORD MW_ADMIN_PASSWORD
: "${MW_CUSTOM_IMAGE:?MW_CUSTOM_IMAGE env var required for update}"
: "${MW_LOCALSETTINGS_HOST_PATH:?MW_LOCALSETTINGS_HOST_PATH env var required for update}"
: "${MW_LOCALSETTINGS_CONTAINER_PATH:?MW_LOCALSETTINGS_CONTAINER_PATH env var required for update}"
: "${MW_LOCAL_MOUNT_DIR:?MW_LOCAL_MOUNT_DIR env var required for update}"
: "${MW_LOCAL_PATH:?MW_LOCAL_PATH env var required for update}"
: "${MW_VOLUME_IMAGES:?MW_VOLUME_IMAGES env var required for update}"
: "${MW_VOLUME_EXTENSIONS:?MW_VOLUME_EXTENSIONS env var required for update}"

MW_NETWORK_OBJSTORE="${MW_NETWORK_OBJSTORE:-}"
objstore_network=()
if [ -n "$MW_NETWORK_OBJSTORE" ] && [ "$MW_NETWORK_OBJSTORE" != "$NETWORK" ]; then
    objstore_network=(--network "$MW_NETWORK_OBJSTORE")
fi

has_tables=0
if MYSQL_PWD="$MW_DB_PASSWORD" container run --rm --network "$NETWORK" -e MYSQL_PWD \
        "mariadb:${MARIADB_VERSION:-latest}" \
        mariadb -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" \
                -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$DB_NAME';" \
        2>/dev/null | grep -q -v '^0$'; then
    has_tables=1
fi

if [ "$has_tables" -eq 0 ]; then
    echo "[mw] Fresh DB detected -> running install (one-shot)"
    # shellcheck disable=SC2016
    container run --rm \
        --network "$NETWORK" \
        -u "$MW_USER" \
        -e MW_DB_PASSWORD \
        -e MW_ADMIN_PASSWORD \
        "$MW_IMAGE:$MW_VERSION" \
        bash -c 'umask 077 && printf "%s" "$MW_DB_PASSWORD" > /tmp/dbpass && printf "%s" "$MW_ADMIN_PASSWORD" > /tmp/pass && exec php "$@" --dbpassfile /tmp/dbpass --passfile /tmp/pass' _ \
            "$MW_HTML_DIR/maintenance/run.php" install \
            --confpath /tmp \
            --dbtype mysql \
            --dbserver "$DB_HOST:$DB_PORT" \
            --dbname "$DB_NAME" \
            --dbuser "$DB_USER" \
            --server "$MW_URL" \
            --scriptpath "" \
            "$MW_SITENAME" \
            "$ADMIN_NAME"
else
    echo "[mw] DB already initialized -> skipping install"
fi

echo "[mw] Running update --quick via one-shot custom-image container"
container run --rm \
    --network "$NETWORK" \
    ${objstore_network[@]+"${objstore_network[@]}"} \
    -u "$MW_USER" \
    -v "${MW_VOLUME_IMAGES}:${MW_HTML_DIR}/images" \
    -v "${MW_VOLUME_EXTENSIONS}:${MW_HTML_DIR}/extensions" \
    -v "${MW_LOCALSETTINGS_HOST_PATH}:${MW_LOCALSETTINGS_CONTAINER_PATH}:ro" \
    -v "${MW_LOCAL_MOUNT_DIR}:${MW_LOCAL_PATH}:ro" \
    "${MW_CUSTOM_IMAGE}" \
    php "${MW_HTML_DIR}/maintenance/run.php" update --quick
