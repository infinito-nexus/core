#!/usr/bin/env bash
set -euo pipefail

: "${BKP_TEST_SERVICE:?}"
: "${BKP_TEST_HEALTH_TIMEOUT:?}"
: "${BKP_TEST_LOCK_TIMEOUT:?}"
: "${BKP_TEST_MAINTENANCE_BIN:?}"
: "${BKP_TEST_MAINTENANCE_FILE:?}"
: "${BKP_TEST_STOPPING?}"
: "${BKP_TEST_STOPPING_PROJECTS?}"

IFS=',' read -r -a STOPPING <<<"${BKP_TEST_STOPPING}"
IFS=',' read -r -a PROJECTS <<<"${BKP_TEST_STOPPING_PROJECTS}"
if (( ${#STOPPING[@]} != ${#PROJECTS[@]} )); then
    echo "FAIL: ${#STOPPING[@]} stopping application(s) but ${#PROJECTS[@]} compose project(s)"
    exit 1
fi

announced() {
    "${BKP_TEST_MAINTENANCE_BIN}" active --file "${BKP_TEST_MAINTENANCE_FILE}" | tr -d '[]" ' | tr ',' '\n' | sed '/^$/d'
}

# Param $1: compose project of an application the run stops
running_in() {
    container ps --filter "label=com.docker.compose.project=$1" --filter status=running -q | wc -l
}

# Param $1: compose project whose running count BASELINE recorded
project_down() {
    (( $(running_in "$1") < ${BASELINE[$1]} ))
}

# Param $1: newline-separated application ids
# Param $2: application id
holds() {
    grep -qxF -- "$2" <<<"$1"
}

if [[ -n "$(announced)" ]]; then
    echo "FAIL: the signal announces $(announced | paste -sd,) before the forced run starts"
    exit 1
fi
echo "maintenance: before the run the signal lists nothing"

declare -A BASELINE=()
for project in "${PROJECTS[@]}"; do
    if [[ -n "${project}" ]]; then
        BASELINE["${project}"]="$(running_in "${project}")"
    fi
done

systemctl start --no-block "${BKP_TEST_SERVICE}"
deadline=$(( $(date +%s) + BKP_TEST_LOCK_TIMEOUT + BKP_TEST_HEALTH_TIMEOUT ))
announcement=""
first_stop=""
cleared=""
while :; do
    state="$(systemctl is-active "${BKP_TEST_SERVICE}" 2>/dev/null || true)"
    current="$(announced)"
    while IFS= read -r application; do
        if [[ -n "${application}" ]] && [[ " ${STOPPING[*]} " != *" ${application} "* ]]; then
            echo "FAIL: the signal names ${application}, which this run never stops"
            exit 1
        fi
    done <<<"${current}"
    if [[ -n "${current}" ]] && [[ -z "${announcement}" ]]; then
        announcement="$(paste -sd, <<<"${current}")"
        if [[ -n "${first_stop}" ]]; then
            echo "FAIL: ${first_stop} stopped before the signal announced ${announcement}"
            exit 1
        fi
        for application in "${STOPPING[@]}"; do
            if [[ -n "${application}" ]] && ! holds "${current}" "${application}"; then
                echo "FAIL: the signal ${announcement} omits ${application}, which this run stops"
                exit 1
            fi
        done
        echo "maintenance: the signal announces ${announcement} before the first stop"
    fi
    for idx in "${!PROJECTS[@]}"; do
        project="${PROJECTS[idx]}"
        if [[ -z "${project}" ]] || ! project_down "${project}"; then
            continue
        fi
        if ! holds "${current}" "${STOPPING[idx]}"; then
            echo "FAIL: project ${project} is down while the signal does not list ${STOPPING[idx]}"
            exit 1
        fi
        if [[ -z "${first_stop}" ]]; then
            first_stop="${project}"
            echo "maintenance: ${project} stopped while the signal listed ${STOPPING[idx]}"
        fi
    done
    if [[ -n "${announcement}" ]] && [[ -z "${current}" ]] && [[ -z "${cleared}" ]]; then
        cleared="yes"
        echo "maintenance: the signal lists nothing once every stopped project runs again"
    fi
    case "${state}" in
        active | activating | deactivating) ;;
        *) break ;;
    esac
    if (( $(date +%s) >= deadline )); then
        echo "FAIL: ${BKP_TEST_SERVICE} still ${state} after the drill's deadline"
        exit 1
    fi
    sleep 0.5
done

if [[ -n "$(announced)" ]]; then
    echo "FAIL: the finished run left the signal at $(announced | paste -sd,)"
    exit 1
fi
for project in "${PROJECTS[@]}"; do
    if [[ -n "${project}" ]] && project_down "${project}"; then
        echo "FAIL: project ${project} is still down after the run"
        exit 1
    fi
done
if [[ -z "${announcement}" ]] && [[ -n "${first_stop}" ]]; then
    echo "FAIL: ${first_stop} went down during a run that announced no stop"
    exit 1
fi
if [[ -z "${announcement}" ]]; then
    echo "maintenance: the run announced no stop and none happened, the snapshot path"
fi
echo "maintenance: the signal leads every stop and trails every start"
