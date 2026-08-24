#!/usr/bin/env bash
# Disaster-recovery drill: record what runs, take the host down, hand the
# generation to the recover chain, bring the host back and require each
# recorded container healthy (or running when it defines no healthcheck).
#
# Databases come back last with only their engine service up - the replay
# pre-cleans in one psql session and a booting consumer would recreate the
# schema before the dump's CREATE TABLE lands. The engine's service name comes
# from its compose label: no fixed name covers both `postgres` (project
# postgres, volume postgres_data) and bigbluebutton (project bigbluebutton,
# service postgres).
#
# Every mounted volume is emptied, including those declared `backup: false` -
# that claim of disposability is what the drill tests. Emptied, not removed:
# docker refuses to remove a volume a container still references, and a
# container outside compose is only stopped here; re-creating a removed volume
# would also drop its driver options. An engine volume whose dump is about to
# be replayed is spared, because `pg_dump -d <db>` writes no CREATE ROLE or
# CREATE DATABASE and initdb would leave nothing to replay into.
#
# Discourse carries no compose label but is a subject when it holds a volume.
set -euo pipefail

: "${BKP_TEST_HEALTH_TIMEOUT:?}"
: "${BKP_TEST_PYTHON:?}"
: "${BKP_TEST_REPO_ROOT:?}"
: "${BKP_TEST_SCRATCH_IMAGE:?}"
: "${DR_TOKEN:?}"
: "${REPO_DIR:?}"
: "${NEWEST_GENERATION:?}"

GEN_DIR="${REPO_DIR}/${NEWEST_GENERATION}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TORN_DOWN_MARKER="${BKP_TEST_REPO_ROOT}/.stack-torn-down"
# shellcheck disable=SC2016
NETWORK_TEMPLATE='{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}'

if [[ "$(container info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null)" == "active" ]]; then
    echo "FAIL: swarm node; test.sh decides this and stops before seeding, so reaching here means the script was invoked directly - the down/up cycle would race the orchestrator"
    exit 1
fi

if [[ ! -d "${BKP_TEST_REPO_ROOT}/cli/administration/recover" ]]; then
    echo "FAIL: no repository checkout at ${BKP_TEST_REPO_ROOT} on this host; the drill restores through the recover CLI, which runs from the checkout"
    exit 1
fi

recover() {
    PYTHONPATH="${BKP_TEST_REPO_ROOT}" python3 -m cli.administration.recover \
        "$1" "$2" localhost --no-safety-backup
}

empty_volume() {
    # shellcheck disable=SC2016
    container run --rm --mount "type=volume,src=$1,dst=/subject" \
        "${BKP_TEST_SCRATCH_IMAGE}" \
        sh -c 'find /subject -mindepth 1 -delete && [ -z "$(ls -A /subject)" ]'
}

SELF_NAME=""
SELF_PROJECT=""
if container inspect --type container "$(hostname)" >/dev/null 2>&1; then
    SELF_NAME="$(container inspect --type container -f '{{.Name}}' "$(hostname)" | sed 's|^/||')"
    SELF_PROJECT="$(container inspect --type container -f '{{index .Config.Labels "com.docker.compose.project"}}' "$(hostname)")"
    echo "OK: excluding own container '${SELF_NAME}' (project '${SELF_PROJECT}') from the cycle"
fi

declare -A PROJECT_DIR=()
declare -A VOLUME_PROJECT=()
declare -A VOLUME_CONTAINER=()
declare -A MOUNTED=()
RUNNING=()
while IFS='|' read -r name project workdir; do
    if [[ -z "${project}" ]] || [[ "${name}" == "${SELF_NAME}" ]] || [[ "${project}" == "${SELF_PROJECT}" ]]; then
        continue
    fi
    RUNNING+=("${name}")
    PROJECT_DIR["${project}"]="${workdir}"
    for volume in $(container inspect --type container -f '{{range .Mounts}}{{if .Name}}{{.Name}} {{end}}{{end}}' "${name}"); do
        VOLUME_PROJECT["${volume}"]="${project}"
        VOLUME_CONTAINER["${volume}"]="${name}"
        MOUNTED["${volume}"]=1
    done
done < <(container ps --format '{{.Names}}|{{.Label "com.docker.compose.project"}}|{{.Label "com.docker.compose.project.working_dir"}}')

if (( ${#RUNNING[@]} < 1 )); then
    echo "FAIL: no running compose containers before the restore cycle"
    exit 1
fi
echo "OK: ${#RUNNING[@]} running container(s) recorded"

BACKED_UP_VOLUMES=" $(find "${GEN_DIR}" -mindepth 2 -maxdepth 2 -type d \( -name files -o -name sql \) -printf '%h\n' | xargs -rn1 basename | sort -u | tr '\n' ' ')"
LOOSE=()
while IFS='|' read -r name project; do
    if [[ -n "${project}" ]] || [[ "${name}" == "${SELF_NAME}" ]]; then
        continue
    fi
    loose_volumes=()
    for volume in $(container inspect --type container -f '{{range .Mounts}}{{if .Name}}{{.Name}} {{end}}{{end}}' "${name}"); do
        loose_volumes+=("${volume}")
    done
    for volume in "${loose_volumes[@]-}"; do
        if [[ -n "${volume}" ]] && [[ "${BACKED_UP_VOLUMES}" == *" ${volume} "* ]]; then
            LOOSE+=("${name}")
            RUNNING+=("${name}")
            for owned in "${loose_volumes[@]}"; do
                MOUNTED["${owned}"]=1
            done
            break
        fi
    done
done < <(container ps --format '{{.Names}}|{{.Label "com.docker.compose.project"}}')
if (( ${#LOOSE[@]} > 0 )); then
    echo "OK: ${#LOOSE[@]} container(s) outside compose hold backed-up volumes: ${LOOSE[*]}"
fi

mapfile -t PROJECTS < <(printf '%s\n' "${!PROJECT_DIR[@]}" | sort)
for project in "${PROJECTS[@]}"; do
    if [[ ! -d "${PROJECT_DIR[${project}]}" ]]; then
        echo "FAIL: compose working dir '${PROJECT_DIR[${project}]}' for running project ${project} does not exist"
        exit 1
    fi
done
echo "OK: ${#PROJECTS[@]} compose project(s) recorded: ${PROJECTS[*]}"

DB_PROJECTS=()
declare -A DB_SERVICE=()
while IFS= read -r sql_file; do
    dump_volume="$(basename "$(dirname "$(dirname "${sql_file}")")")"
    owner="${VOLUME_PROJECT[${dump_volume}]:-}"
    if [[ -z "${owner}" ]]; then
        echo "FAIL: no running container mounts volume ${dump_volume}, which holds $(basename "${sql_file}"); its database service is not part of this host"
        exit 1
    fi
    engine_container="${VOLUME_CONTAINER[${dump_volume}]}"
    engine_service="$(container inspect --type container -f '{{index .Config.Labels "com.docker.compose.service"}}' "${engine_container}")"
    if [[ -z "${engine_service}" ]]; then
        echo "FAIL: ${engine_container} mounts ${dump_volume} but carries no compose service label, so the engine cannot be started without its consumers"
        exit 1
    fi
    DB_SERVICE["${owner}"]="${engine_service}"
    if [[ " ${DB_PROJECTS[*]-} " != *" ${owner} "* ]]; then
        DB_PROJECTS+=("${owner}")
    fi
done < <(find "${GEN_DIR}" -mindepth 3 -maxdepth 3 -type f -path '*/sql/*.backup.sql' | sort)
echo "OK: ${#DB_PROJECTS[@]} database project(s) hold the dumps: ${DB_PROJECTS[*]-none}"
for project in "${DB_PROJECTS[@]}"; do
    echo "OK: only service '${DB_SERVICE[${project}]}' of project ${project} comes up for the replay"
done

mapfile -t VOLUME_DIRS < <(find "${GEN_DIR}" -mindepth 2 -maxdepth 2 -type d -name files | sort)
RESTORABLE=()
for volume_dir in "${VOLUME_DIRS[@]}"; do
    RESTORABLE+=("$(basename "$(dirname "${volume_dir}")")")
done
echo "OK: ${#RESTORABLE[@]} volume(s) come back from this generation: ${RESTORABLE[*]-none}"

DUMP_VOLUMES=" $(find "${GEN_DIR}" -mindepth 2 -maxdepth 2 -type d -name sql -printf '%h\n' | xargs -rn1 basename | sort -u | tr '\n' ' ')"
DISCARD=()
SPARED=()
for volume in "${!MOUNTED[@]}"; do
    if [[ "${DUMP_VOLUMES}" != *" ${volume} "* ]]; then
        DISCARD+=("${volume}")
    else
        SPARED+=("${volume}")
    fi
done
mapfile -t DISCARD < <(printf '%s\n' "${DISCARD[@]-}" | grep -v '^$' | sort)
mapfile -t SPARED < <(printf '%s\n' "${SPARED[@]-}" | grep -v '^$' | sort)
echo "OK: ${#DISCARD[@]} volume(s) get emptied: ${DISCARD[*]-none}"
if (( ${#SPARED[@]} > 0 )); then
    echo "NOTE: ${#SPARED[@]} engine data director(ies) are NOT emptied: ${SPARED[*]}"
    echo "NOTE: their dumps carry no CREATE ROLE and no CREATE DATABASE, so an emptied engine would come back from initdb with nothing to replay into; this drill proves the dump, not the engine's own volume"
fi
UNRESTORABLE=()
for volume in "${DISCARD[@]-}"; do
    if [[ -n "${volume}" ]] && [[ " ${RESTORABLE[*]-} " != *" ${volume} "* ]]; then
        UNRESTORABLE+=("${volume}")
    fi
done
if (( ${#UNRESTORABLE[@]} > 0 )); then
    echo "NOTE: ${#UNRESTORABLE[@]} of them are not in the backup and must be rebuilt by their own service: ${UNRESTORABLE[*]}"
fi

declare -A NETWORKS=()
for name in "${RUNNING[@]}"; do
    NETWORKS["${name}"]="$(container inspect --type container -f "${NETWORK_TEMPLATE}" "${name}")"
done
echo "OK: network attachments recorded for ${#NETWORKS[@]} container(s)"

# Any exit between this teardown and the final restart leaves the host with
# its subjects down, which is why the marker is written from a trap.
mark_torn_down() {
    local code=$?
    if (( code != 0 )); then
        printf 'the backup drill tore this host down and exited %s before restarting it\n' \
            "${code}" >"${TORN_DOWN_MARKER}"
        echo "FAIL: subjects are left down; recorded in ${TORN_DOWN_MARKER}" >&2
    fi
}
trap mark_torn_down EXIT

echo "Stopping every subject of this host..."
for project in "${PROJECTS[@]}"; do
    compose --chdir "${PROJECT_DIR[${project}]}" --project "${project}" down --remove-orphans
done
for name in "${LOOSE[@]-}"; do
    if [[ -n "${name}" ]]; then
        container stop "${name}"
    fi
done
for name in "${RUNNING[@]}"; do
    if [[ "$(container inspect --type container -f '{{.State.Status}}' "${name}" 2>/dev/null || echo gone)" == "running" ]]; then
        echo "FAIL: ${name} still running after the teardown"
        exit 1
    fi
done
echo "OK: every subject of this host is down"

for volume in "${DISCARD[@]-}"; do
    if [[ -n "${volume}" ]]; then
        empty_volume "${volume}"
    fi
done
echo "OK: ${#DISCARD[@]} volume(s) emptied and proven empty"

for project in "${PROJECTS[@]}"; do
    compose --chdir "${PROJECT_DIR[${project}]}" --project "${project}" create
done
for volume in "${RESTORABLE[@]-}"; do
    if [[ -n "${volume}" ]] && ! container volume inspect "${volume}" >/dev/null 2>&1; then
        echo "FAIL: volume ${volume} is in the generation but does not exist on this host, so its restore would have nowhere to land"
        exit 1
    fi
done

"${BKP_TEST_PYTHON}" "${DIR}/seed/marker.py" blank "${GEN_DIR}" "${DR_TOKEN}"

echo "Restoring ${#VOLUME_DIRS[@]} volume(s) from generation ${NEWEST_GENERATION}"
for volume_dir in "${VOLUME_DIRS[@]}"; do
    recover volume "${volume_dir}"
done

start_projects() {
    local round project up_failed
    local -A pids
    local -a only
    for round in 1 2 3; do
        up_failed=0
        pids=()
        for project in "$@"; do
            only=()
            if [[ -n "${DB_SERVICE[${project}]:-}" ]]; then
                only=("${DB_SERVICE[${project}]}")
            fi
            compose --chdir "${PROJECT_DIR[${project}]}" --project "${project}" up -d "${only[@]}" &
            pids["${project}"]=$!
        done
        for project in "${!pids[@]}"; do
            if ! wait "${pids[${project}]}"; then
                echo "WARN: up failed for ${project} (round ${round})"
                up_failed=$((up_failed + 1))
            fi
        done
        if (( up_failed == 0 )); then
            return 0
        fi
        sleep 60
    done
    echo "FAIL: ${up_failed} project(s) failed to start after 3 rounds"
    exit 1
}

if (( ${#DB_PROJECTS[@]} > 0 )); then
    echo "Starting the database projects, every consumer stays down..."
    start_projects "${DB_PROJECTS[@]}"
    db_deadline=$(( $(date +%s) + BKP_TEST_HEALTH_TIMEOUT ))
    for project in "${DB_PROJECTS[@]}"; do
        for name in $(container ps --filter "label=com.docker.compose.project=${project}" --format '{{.Names}}'); do
            while :; do
                read -r status health <<<"$(container inspect --type container -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${name}")"
                if [[ "${health}" == "healthy" ]]; then
                    echo "OK: ${name} accepts connections (${status}/${health})"
                    break
                fi
                if [[ "${health}" == "none" ]]; then
                    echo "FAIL: ${name} defines no healthcheck, so nothing states when the engine accepts connections"
                    exit 1
                fi
                if (( $(date +%s) >= db_deadline )); then
                    echo "FAIL: ${name} is ${status}/${health} after ${BKP_TEST_HEALTH_TIMEOUT}s, the replay would hit an unready engine"
                    container ps -a --format 'table {{.Names}}\t{{.Status}}'
                    exit 1
                fi
                sleep 5
            done
        done
    done
    recover database "${GEN_DIR}"
fi

"${BKP_TEST_PYTHON}" "${DIR}/seed/marker.py" verify "${GEN_DIR}" "${DR_TOKEN}"

DB_SERVICE=()
echo "Starting every project to completion..."
start_projects "${PROJECTS[@]}"
for name in "${LOOSE[@]-}"; do
    if [[ -n "${name}" ]]; then
        container start "${name}"
    fi
done

for name in "${!NETWORKS[@]}"; do
    attached="$(container inspect --type container -f "${NETWORK_TEMPLATE}" "${name}" 2>/dev/null)" || continue
    for network in ${NETWORKS[${name}]}; do
        if [[ " ${attached} " != *" ${network} "* ]]; then
            container network connect "${network}" "${name}"
            echo "OK: re-attached ${name} to ${network}, which compose does not own"
        fi
    done
done

DEADLINE=$(( $(date +%s) + BKP_TEST_HEALTH_TIMEOUT ))
NOHC_NAMES=()
NOHC_RESTARTS=()
for name in "${RUNNING[@]}"; do
    while :; do
        state="$(container inspect --type container -f '{{.State.Status}} {{.State.ExitCode}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${name}" 2>/dev/null)" || {
            echo "FAIL: ${name} did not come back after the restore"
            exit 1
        }
        read -r status exit_code health <<<"${state}"
        if [[ "${health}" == "healthy" ]] || { [[ "${health}" == "none" ]] && [[ "${status}" == "running" ]]; }; then
            if [[ "${health}" == "none" ]]; then
                NOHC_NAMES+=("${name}")
                NOHC_RESTARTS+=("$(container inspect --type container -f '{{.RestartCount}}' "${name}" 2>/dev/null || echo -1)")
            fi
            echo "OK: ${name} ${status}/${health}"
            break
        fi
        if [[ "${status}" == "exited" ]] && [[ "${exit_code}" == "0" ]]; then
            echo "OK: ${name} oneshot exited 0"
            break
        fi
        if (( $(date +%s) >= DEADLINE )); then
            echo "FAIL: ${name} is ${status}/${health} after ${BKP_TEST_HEALTH_TIMEOUT}s"
            container ps -a --format 'table {{.Names}}\t{{.Status}}'
            exit 1
        fi
        sleep 5
    done
done

if (( ${#NOHC_NAMES[@]} > 0 )); then
    sleep 15
    for idx in "${!NOHC_NAMES[@]}"; do
        name="${NOHC_NAMES[idx]}"
        state="$(container inspect --type container -f '{{.State.Status}} {{.State.ExitCode}} {{.RestartCount}}' "${name}" 2>/dev/null || echo "gone -1 -1")"
        read -r status exit_code restarts <<<"${state}"
        if [[ "${status}" == "exited" ]] && [[ "${exit_code}" == "0" ]]; then
            continue
        fi
        if [[ "${status}" != "running" ]] || [[ "${restarts}" != "${NOHC_RESTARTS[idx]}" ]]; then
            echo "FAIL: ${name} is crash-looping (status ${status}, restarts ${NOHC_RESTARTS[idx]} -> ${restarts})"
            exit 1
        fi
    done
    echo "OK: ${#NOHC_NAMES[@]} container(s) without healthcheck stable for 15s"
fi

trap - EXIT
rm -f "${TORN_DOWN_MARKER}"
echo "OK: all restored containers healthy"
