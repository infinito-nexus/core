#!/usr/bin/env bash
# Update runs as a one-shot throwaway container, not `container exec` against
# the live task: under swarm a not-yet-installed task can be reaped by the
# healthcheck mid-update otherwise.
set -euo pipefail

NETWORK="$1"; MARIADB_VERSION="$2"
DB_HOST="$3"; DB_PORT="$4"; DB_USER="$5"; DB_PASSWORD="$6"; DB_NAME="$7"
MW_USER="$8"; MW_IMAGE="$9"; MW_VERSION="${10}"; MW_HTML_DIR="${11}"
MW_URL="${12}"; MW_SITENAME="${13}"; ADMIN_NAME="${14}"; ADMIN_PASSWORD="${15}"

: "${MW_CUSTOM_IMAGE:?MW_CUSTOM_IMAGE env var required for update}"
: "${MW_LOCALSETTINGS_HOST_PATH:?MW_LOCALSETTINGS_HOST_PATH env var required for update}"
: "${MW_LOCALSETTINGS_CONTAINER_PATH:?MW_LOCALSETTINGS_CONTAINER_PATH env var required for update}"
: "${MW_LOCAL_MOUNT_DIR:?MW_LOCAL_MOUNT_DIR env var required for update}"
: "${MW_LOCAL_PATH:?MW_LOCAL_PATH env var required for update}"
: "${MW_VOLUME_IMAGES:?MW_VOLUME_IMAGES env var required for update}"
: "${MW_VOLUME_EXTENSIONS:?MW_VOLUME_EXTENSIONS env var required for update}"

has_tables=0
if container run --rm --network "$NETWORK" "mariadb:${MARIADB_VERSION:-latest}" \
        mariadb -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" \
                -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$DB_NAME';" \
        2>/dev/null | grep -q -v '^0$'; then
    has_tables=1
fi

if [ "$has_tables" -eq 0 ]; then
    echo "[mw] Fresh DB detected -> running install (one-shot)"
    container run --rm \
        --network "$NETWORK" \
        -u "$MW_USER" \
        "$MW_IMAGE:$MW_VERSION" \
        php "$MW_HTML_DIR/maintenance/run.php" install \
            --confpath /tmp \
            --dbtype mysql \
            --dbserver "$DB_HOST:$DB_PORT" \
            --dbname "$DB_NAME" \
            --dbuser "$DB_USER" \
            --dbpass "$DB_PASSWORD" \
            --server "$MW_URL" \
            --scriptpath "" \
            "$MW_SITENAME" \
            "$ADMIN_NAME" \
            --pass "$ADMIN_PASSWORD"
else
    echo "[mw] DB already initialized -> skipping install"
fi

echo "[mw] Running update --quick via one-shot custom-image container"
container run --rm \
    --network "$NETWORK" \
    -u "$MW_USER" \
    -v "${MW_VOLUME_IMAGES}:${MW_HTML_DIR}/images" \
    -v "${MW_VOLUME_EXTENSIONS}:${MW_HTML_DIR}/extensions" \
    -v "${MW_LOCALSETTINGS_HOST_PATH}:${MW_LOCALSETTINGS_CONTAINER_PATH}:ro" \
    -v "${MW_LOCAL_MOUNT_DIR}:${MW_LOCAL_PATH}:ro" \
    "${MW_CUSTOM_IMAGE}" \
    php "${MW_HTML_DIR}/maintenance/run.php" update --quick
