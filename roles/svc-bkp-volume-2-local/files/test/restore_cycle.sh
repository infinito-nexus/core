#!/usr/bin/env bash
# Disaster-recovery drill against the newest backup generation:
# compose-down every running project, wipe each backed-up volume, restore
# it via baudolo-restore, compose-up the projects again and require every
# previously running container healthy (or running when it defines no
# healthcheck).
set -euo pipefail

: "${BKP_TEST_BACKUPS_DIR:?}"
: "${BKP_TEST_RESTORE_BIN:?}"
: "${BKP_TEST_HEALTH_TIMEOUT:?}"
: "${MACHINE_HASH:?}"
: "${REPO_DIR:?}"
: "${REPO_NAME:?}"
: "${NEWEST_GENERATION:?}"

GEN_DIR="${REPO_DIR}/${NEWEST_GENERATION}"

if [[ "$(container info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null)" == "active" ]]; then
    echo "SKIP: swarm node detected; the compose down/up cycle races the orchestrator's reconciler, the drill only supports compose hosts"
    exit 0
fi

SELF_NAME=""
SELF_PROJECT=""
if container inspect "$(hostname)" >/dev/null 2>&1; then
    SELF_NAME="$(container inspect -f '{{.Name}}' "$(hostname)" | sed 's|^/||')"
    SELF_PROJECT="$(container inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$(hostname)")"
    echo "OK: excluding own container '${SELF_NAME}' (project '${SELF_PROJECT}') from the cycle"
fi

mapfile -t RUNNING < <(container ps --format '{{.Names}}\t{{.Label "com.docker.compose.project"}}' |
    awk -F'\t' -v self="${SELF_PROJECT}" -v selfname="${SELF_NAME}" \
        '$1 != selfname && $2 != "" && (self == "" || $2 != self) { print $1 }')
if (( ${#RUNNING[@]} < 1 )); then
    echo "FAIL: no running compose containers before the restore cycle"
    exit 1
fi
echo "OK: ${#RUNNING[@]} running container(s) recorded"

declare -A PROJECT_DIR
while IFS=$'\t' read -r project workdir; do
    if [[ -z "${project}" ]] || [[ "${project}" == "${SELF_PROJECT}" ]]; then
        continue
    fi
    PROJECT_DIR["${project}"]="${workdir}"
done < <(container ps --filter label=com.docker.compose.project \
    --format '{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.project.working_dir"}}' |
    sort -u)
if (( ${#PROJECT_DIR[@]} < 1 )); then
    echo "FAIL: no compose projects found to cycle"
    exit 1
fi
mapfile -t PROJECTS < <(printf '%s\n' "${!PROJECT_DIR[@]}" | sort)
for project in "${PROJECTS[@]}"; do
    if [[ ! -d "${PROJECT_DIR[${project}]}" ]]; then
        echo "FAIL: compose working dir '${PROJECT_DIR[${project}]}' for running project ${project} does not exist"
        exit 1
    fi
done
echo "OK: ${#PROJECTS[@]} compose project(s) recorded: ${PROJECTS[*]}"


echo "Stopping compose projects..."
for project in "${PROJECTS[@]}"; do
    compose --chdir "${PROJECT_DIR[${project}]}" --project "${project}" down --remove-orphans
done
for name in "${RUNNING[@]}"; do
    if [[ "$(container inspect -f '{{.State.Status}}' "${name}" 2>/dev/null || echo gone)" == "running" ]]; then
        echo "FAIL: ${name} still running after compose down"
        exit 1
    fi
done
echo "OK: all compose projects down"

mapfile -t VOLUMES < <(find "${GEN_DIR}" -mindepth 2 -maxdepth 2 -type d -name files -printf '%h\n' | sort | xargs -rn1 basename)
echo "Restoring ${#VOLUMES[@]} volume(s) from generation ${NEWEST_GENERATION}"

for volume in "${VOLUMES[@]}"; do
    if ! container volume inspect "${volume}" >/dev/null 2>&1; then
        echo "SKIP: volume ${volume} does not exist on this host"
        continue
    fi
    _wipe_mp="$(container volume inspect --format '{{ .Mountpoint }}' "${volume}")"
    rm -rf "${_wipe_mp:?}"/* "${_wipe_mp}"/.[!.]* "${_wipe_mp}"/..?* 2>/dev/null || true
    if [[ -n "$(find "${_wipe_mp}" -mindepth 1 -print -quit)" ]]; then
        echo "FAIL: volume ${volume} not empty after wipe"
        exit 1
    fi
    "${BKP_TEST_RESTORE_BIN}" files "${volume}" "${MACHINE_HASH}" "${NEWEST_GENERATION}" \
        --backups-dir "${BKP_TEST_BACKUPS_DIR}" \
        --repo-name "${REPO_NAME}"
    echo "OK: restored ${volume}"
done

echo "Starting compose projects..."
up_failed=0
for round in 1 2 3; do
    up_failed=0
    declare -A UP_PID=()
    for project in "${PROJECTS[@]}"; do
        compose --chdir "${PROJECT_DIR[${project}]}" --project "${project}" up -d &
        UP_PID["${project}"]=$!
    done
    for project in "${!UP_PID[@]}"; do
        if ! wait "${UP_PID[${project}]}"; then
            echo "WARN: up failed for ${project} (round ${round})"
            up_failed=$((up_failed + 1))
        fi
    done
    if (( up_failed == 0 )); then
        break
    fi
    sleep 60
done
if (( up_failed > 0 )); then
    echo "FAIL: ${up_failed} project(s) failed to start after 3 rounds"
    exit 1
fi

DEADLINE=$(( $(date +%s) + BKP_TEST_HEALTH_TIMEOUT ))
NOHC_NAMES=()
NOHC_RESTARTS=()
for name in "${RUNNING[@]}"; do
    while :; do
        state="$(container inspect -f '{{.State.Status}} {{.State.ExitCode}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${name}" 2>/dev/null)" || {
            echo "GONE: ${name} disappeared during health wait"
            break
        }
        read -r status exit_code health <<<"${state}"
        if [[ "${health}" == "healthy" ]] || { [[ "${health}" == "none" ]] && [[ "${status}" == "running" ]]; }; then
            if [[ "${health}" == "none" ]]; then
                NOHC_NAMES+=("${name}")
                NOHC_RESTARTS+=("$(container inspect -f '{{.RestartCount}}' "${name}" 2>/dev/null || echo -1)")
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
        state="$(container inspect -f '{{.State.Status}} {{.State.ExitCode}} {{.RestartCount}}' "${name}" 2>/dev/null || echo "gone -1 -1")"
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
echo "OK: all restored containers healthy"
