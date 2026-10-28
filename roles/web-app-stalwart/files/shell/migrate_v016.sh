#!/usr/bin/env bash
# Param $1: upgrade | check | backup | target | prepare | sync | final | status | all, the steps of "Upgrading from 0.16" in roles/web-app-stalwart/README.md.
# Param migrate.env: the values the deploy rendered next to this script.
set -euo pipefail
umask 077

HERE="$(dirname "$(readlink -f "$0")")"
readonly HERE
readonly ENV_FILE="${HERE}/migrate.env"
readonly UPGRADE_OVERRIDE="${HERE}/compose.upgrade.yml"
readonly SOURCE_MOUNT=/migrate/source
readonly TARGET_MOUNT=/migrate/target
readonly STATE_MOUNT=/migrate/state
readonly HEALTH_TIMEOUT_SECONDS=300

# shellcheck source=/dev/null
source "$ENV_FILE"

die() {
  echo "migrate: $*" >&2
  exit 1
}

stop_stalwart() {
  if [ "$DEPLOYMENT_MODE" = "swarm" ]; then
    container service scale "${STALWART_SERVICE:?}=0"
  else
    container stop "$STALWART_CONTAINER"
  fi
}

start_stalwart() {
  if [ "$DEPLOYMENT_MODE" = "swarm" ]; then
    container service scale "${STALWART_SERVICE:?}=1"
  else
    container start "$STALWART_CONTAINER"
  fi
}

psql_admin() {
  container exec -i "$PG_ADDRESS" psql -X -q -v ON_ERROR_STOP=1 -U "$PG_ADMIN" -d "$1" -At -c "$2"
}

database_exists() {
  [ "$(psql_admin postgres "SELECT count(*) FROM pg_database WHERE datname = '$1'")" = "1" ]
}

migrate() {
  local tty=()
  if [ -t 0 ] && [ -t 1 ]; then
    tty=(-it)
  fi
  container run --rm "${tty[@]}" --user 0:0 --network "$NETWORK" \
    -v "${SOURCE_DIR}:${SOURCE_MOUNT}:ro" \
    -v "${TARGET_DIR}:${TARGET_MOUNT}:ro" \
    -v "${STATE_DIR}:${STATE_MOUNT}" \
    "$IMAGE" "$@"
}

read_series() {
  local banner
  banner="$(container run --rm --user 0:0 "$IMAGE" --help)"
  banner="${banner%%$'\n'*}"
  [[ "$banner" =~ Stalwart\ (v[0-9]+\.[0-9]+)\ deployment\ to\ (v[0-9]+\.[0-9]+) ]] \
    || die "${IMAGE} does not name its source and target series in '${banner}'"
  SOURCE_SERIES="${BASH_REMATCH[1]}"
  TARGET_SERIES="${BASH_REMATCH[2]}"
}

running_image() {
  container inspect --type container --format '{{.Config.Image}}' "$STALWART_ADDRESS" \
    || die "no Stalwart container found; start the stack this host last deployed"
}

running_image_id() {
  container inspect --type container --format '{{.Image}}' "$STALWART_ADDRESS"
}

required_image() {
  local current
  current="$(running_image)"
  echo "${current%:*}:${SOURCE_SERIES}"
}

pull_required_image_id() {
  container pull -q "$(required_image)" > /dev/null
  container image inspect --format '{{.Id}}' "$(required_image)"
}

wait_healthy() {
  local deadline status
  deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
  while [ "$SECONDS" -lt "$deadline" ]; do
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    status="$(container inspect --type container --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$STALWART_ADDRESS" 2> /dev/null || true)" # nocheck: shell-or-true  the container is being recreated, a missing one is retried until the deadline
    case "$status" in
      healthy | running) return 0 ;;
    esac
    sleep 5
  done
  die "Stalwart did not become healthy within ${HEALTH_TIMEOUT_SECONDS}s after the upgrade"
}

phase_upgrade() {
  read_series
  local current required required_id
  current="$(running_image)"
  [[ "${current##*:}" == "${SOURCE_SERIES}."* || "${current##*:}" == "${SOURCE_SERIES}" ]] \
    || die "Stalwart runs ${current}, outside the ${SOURCE_SERIES} series that ${IMAGE} migrates"
  required="$(required_image)"
  required_id="$(pull_required_image_id)"
  if [ "$(running_image_id)" = "$required_id" ]; then
    echo "upgrade: ${current} already is the last ${SOURCE_SERIES} release"
    return 0
  fi
  if [ "$DEPLOYMENT_MODE" = "swarm" ]; then
    container service update --image "$required" "${STALWART_SERVICE:?}"
  else
    printf 'services:\n  %s:\n    image: "%s"\n' "$COMPOSE_SERVICE" "$required" > "$UPGRADE_OVERRIDE"
    compose --chdir "$STACK_DIR" -f "$UPGRADE_OVERRIDE" up -d "$COMPOSE_SERVICE"
  fi
  wait_healthy
  [ "$(running_image_id)" = "$required_id" ] || die "Stalwart still runs ${current} after the upgrade to ${required}"
  echo "upgrade: ${current} -> ${required}"
}

phase_check() {
  read_series
  local current required_id networks
  current="$(running_image)"
  required_id="$(pull_required_image_id)"
  [ "$(running_image_id)" = "$required_id" ] \
    || die "Stalwart runs ${current}, not the last ${SOURCE_SERIES} release $(required_image); run the upgrade phase first"
  [[ "$TARGET_VERSION" == "${TARGET_SERIES}."* ]] \
    || die "the role deploys Stalwart ${TARGET_VERSION}, but ${IMAGE} writes ${TARGET_SERIES} stores"
  # shellcheck disable=SC2016
  networks="$(container inspect --type container --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}} {{end}}' "$STALWART_ADDRESS")"
  [[ " ${networks} " == *" ${NETWORK} "* ]] \
    || die "Stalwart is attached to '${networks}', not to the database network ${NETWORK}"
  ! database_exists "$DB_V016" || die "database ${DB_V016} exists, the swap ran already"
  [ "$(psql_admin "$DB" "$LAYOUT_SQL")" = "bigint" ] || die "database ${DB} holds no 0.16 store"
  [ ! -e "$MARKER" ] || die "${MARKER} marks this host as migrated; remove it only if the store really is 0.16"
  echo "check: ${current} is the last ${SOURCE_SERIES} release on a 0.16 store in database ${DB}; ${IMAGE} writes ${TARGET_SERIES} for ${TARGET_VERSION}; network ${NETWORK}"
}

phase_backup() {
  mkdir -p "$(dirname "$BACKUP_FILE")"
  container exec "$PG_ADDRESS" pg_dump -Fc -U "$PG_ADMIN" -d "$DB" > "${BACKUP_FILE}.part"
  mv "${BACKUP_FILE}.part" "$BACKUP_FILE"
  echo "backup: ${BACKUP_FILE} ($(du -h "$BACKUP_FILE" | cut -f1))"
}

phase_target() {
  if database_exists "$DB_V1"; then
    echo "target: database ${DB_V1} exists, the next sync continues it"
  else
    psql_admin postgres "CREATE DATABASE \"${DB_V1}\" OWNER \"${DB_OWNER}\""
    echo "target: created database ${DB_V1} owned by ${DB_OWNER}"
  fi
}

accept_recommended_answers() {
  local answers="${STATE_DIR}/answers.toml"
  [ -f "$answers" ] || die "prepare wrote no ${answers}"
  awk '
    /^# Not answered yet: uncomment the table to accept the recommended values\.$/ { open = 1; print; next }
    open && /^# / { sub(/^# /, ""); print; next }
    { open = 0; print }
  ' "$answers" > "${answers}.part"
  mv "${answers}.part" "$answers"
}

phase_prepare() {
  mkdir -p "$STATE_DIR"
  if [ -t 0 ] && [ -t 1 ]; then
    migrate prepare --source "${SOURCE_MOUNT}/config.json" --state "$STATE_MOUNT"
    return 0
  fi
  if ! migrate prepare --source "${SOURCE_MOUNT}/config.json" --state "$STATE_MOUNT" --non-interactive; then
    accept_recommended_answers
    migrate prepare --source "${SOURCE_MOUNT}/config.json" --state "$STATE_MOUNT" --non-interactive \
      || die "questions remain open after accepting the recommended answers; run prepare on a terminal"
    echo "prepare: accepted the recommended answers in ${STATE_DIR}/answers.toml"
  fi
}

phase_sync() {
  migrate run --source "${SOURCE_MOUNT}/config.json" --target "${TARGET_MOUNT}/config.json" --state "$STATE_MOUNT"
}

phase_final() {
  phase_check
  stop_stalwart
  if ! migrate run --final --yes --source "${SOURCE_MOUNT}/config.json" --target "${TARGET_MOUNT}/config.json" --state "$STATE_MOUNT"; then
    start_stalwart
    die "the final run failed and nothing was swapped; Stalwart 0.16 serves again, see ${STATE_DIR}/final-report.txt"
  fi
  psql_admin postgres "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('${DB}', '${DB_V1}') AND pid <> pg_backend_pid()" > /dev/null
  psql_admin postgres "ALTER DATABASE \"${DB}\" RENAME TO \"${DB_V016}\""
  if ! psql_admin postgres "ALTER DATABASE \"${DB_V1}\" RENAME TO \"${DB}\""; then
    psql_admin postgres "ALTER DATABASE \"${DB_V016}\" RENAME TO \"${DB}\""
    start_stalwart
    die "renaming ${DB_V1} to ${DB} failed; ${DB} is the 0.16 store again and Stalwart 0.16 serves it"
  fi
  [ "$(psql_admin "$DB" "$LAYOUT_SQL")" = "bytea" ] || die "database ${DB} does not hold a 1.x store after the swap"
  echo "final: ${DB} holds the 1.x store, ${DB_V016} the 0.16 one; deploy web-app-stalwart next"
}

phase_status() {
  migrate status --state "$STATE_MOUNT"
}

phase_all() {
  phase_upgrade
  phase_check
  phase_backup
  phase_target
  phase_prepare
  phase_sync
  phase_final
}

case "${1:-}" in
  upgrade | check | backup | target | prepare | sync | final | status | all)
    "phase_$1"
    ;;
  *)
    echo "usage: $0 upgrade|check|backup|target|prepare|sync|final|status|all" >&2
    exit 2
    ;;
esac
