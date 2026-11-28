#!/usr/bin/env bash
# Param $1: prepare, prove <restore start epoch>, controls or cleanup
set -euo pipefail

: "${BKP_TEST_PYTHON:?}"
: "${BKP_TEST_HEALTH_TIMEOUT:?}"
: "${BKP_TEST_WORKSPACE_DIR:?}"
: "${BKP_TEST_WORKSPACE_CATALOGS:?}"
if [[ -z "${BKP_TEST_WORKSPACE_ORDER:-}" ]]; then
    echo "FAIL: workspace drill: BKP_TEST_WORKSPACE_ORDER holds no provision order for the Incus e2e target"
    exit 1
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="${BKP_TEST_WORKSPACE_DIR}"
NO_CHANGE='No changes\.|0 to add, 0 to change, 0 to destroy|Resources: 0 added, 0 changed, 0 destroyed'
CONTROL_WINDOW=30
IDS=()
if [[ -s "${STATE}/ids" ]]; then
    mapfile -t IDS <"${STATE}/ids"
fi

drill() {
    "${BKP_TEST_PYTHON}" -I "${HERE}/drill.py" "$@"
}

# Param $1: compose project
project_dir() {
    container ps -a --filter "label=com.docker.compose.project=$1" \
        --format '{{.Label "com.docker.compose.project.working_dir"}}' | sed -n '1p'
}

# Param $1: compose project
wait_healthy() {
    local deadline name health
    deadline=$(( $(date +%s) + BKP_TEST_HEALTH_TIMEOUT ))
    for name in $(container ps -a --filter "label=com.docker.compose.project=$1" --format '{{.Names}}'); do
        while :; do
            health="$(container inspect --type container -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${name}")"
            if [[ "${health}" == "running/healthy" ]] || [[ "${health}" == "running/none" ]]; then
                break
            fi
            if (( $(date +%s) >= deadline )); then
                echo "FAIL: workspace drill: ${name} is ${health} after ${BKP_TEST_HEALTH_TIMEOUT}s"
                exit 1
            fi
            sleep 5
        done
    done
}

# Param $1: compose project
# Param $2: env var its env file loses until restore_env puts it back
blank_env() {
    local dir file
    dir="$(project_dir "$1")"
    file="$(grep -rlE "^$2=" "${dir}" | sed -n '1p')"
    if [[ -z "${file}" ]]; then
        echo "FAIL: workspace drill: no env file of project $1 under ${dir} sets $2"
        exit 1
    fi
    cp -p "${file}" "${STATE}/$1.env"
    printf '%s\n' "${file}" >"${STATE}/$1.path"
    grep -vE "^$2=" "${STATE}/$1.env" >"${file}"
    compose --chdir "${dir}" --project "$1" up -d --force-recreate
}

# Param $1: compose project whose env file blank_env emptied
restore_env() {
    local file
    if [[ ! -f "${STATE}/$1.path" ]]; then
        return 0
    fi
    file="$(cat "${STATE}/$1.path")"
    cat "${STATE}/$1.env" >"${file}"
    rm -f "${STATE}/$1.env" "${STATE}/$1.path"
    compose --chdir "$(project_dir "$1")" --project "$1" up -d --force-recreate
    wait_healthy "$1"
}

restore_all() {
    restore_env semaphore
    restore_env openbao
}

prepare() {
    local ws
    : >"${STATE}/ids"
    for ws in "$(cat /proc/sys/kernel/random/uuid)" "$(cat /proc/sys/kernel/random/uuid)"; do
        drill workspace apply "${ws}" "${STATE}/result-${ws}.json"
        printf '%s\n' "${ws}" >>"${STATE}/ids"
        drill repository create "${STATE}/result-${ws}.json" "provision-incus ws-${ws}"
    done
    mapfile -t IDS <"${STATE}/ids"
    echo "workspace drill: step 1 created the workspaces ${IDS[*]} and their repositories"
    drill order "${STATE}/result-${IDS[0]}.json" "provision-incus ws-${IDS[0]}" "${BKP_TEST_WORKSPACE_CATALOGS}/incus.json"
    drill task "${STATE}/result-${IDS[0]}.json" "provision-incus ws-${IDS[0]}" "${STATE}/provision-before.log"
    echo "workspace drill: step 2 provisioned one server of ${IDS[0]} through the Incus e2e target"
    drill state "${IDS[@]}" >"${STATE}/before.json"
    echo "workspace drill: recorded what the backup must bring back"
}

# Param $1: epoch second the restore cycle started its teardown
prove() {
    local started="$1" ws
    : "${REPO_DIR:?}"
    : "${NEWEST_GENERATION:?}"
    echo "workspace drill: step 3 generation ${NEWEST_GENERATION} holds $(find "${REPO_DIR}/${NEWEST_GENERATION}" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort | paste -sd' ')"
    echo "workspace drill: step 4 every project went down and came back from generation ${NEWEST_GENERATION}"
    for ws in "${IDS[@]}"; do
        drill workspace apply "${ws}" "${STATE}/result-${ws}.json"
    done
    echo "workspace drill: step 5 workspace apply ran for ${IDS[*]}"
    echo "workspace drill: restore took $(( $(date +%s) - started ))s"
    drill state "${IDS[@]}" >"${STATE}/after.json"
    drill check "${STATE}/before.json" "${STATE}/after.json"
    drill task "${STATE}/result-${IDS[0]}.json" "provision-incus ws-${IDS[0]}" "${STATE}/provision-after.log"
    echo "workspace drill: a workspace task clones its repository with the key stored in Semaphore"
    if ! grep -qE "${NO_CHANGE}" "${STATE}/provision-after.log"; then
        echo "FAIL: workspace drill: tofu reports a change after the restore, see ${STATE}/provision-after.log"
        exit 1
    fi
    echo "workspace drill: the transit key decrypts the state and tofu plan reports no change"
}

controls() {
    local deadline
    trap restore_all EXIT
    blank_env semaphore SEMAPHORE_ACCESS_KEY_ENCRYPTION
    wait_healthy semaphore
    rm -f "${STATE}/control-clone.log"
    if drill task "${STATE}/result-${IDS[0]}.json" "provision-incus ws-${IDS[0]}" "${STATE}/control-clone.log"; then
        echo "FAIL: workspace drill: the task cloned without the access key encryption key"
        exit 1
    fi
    if [[ ! -f "${STATE}/control-clone.log" ]]; then
        echo "FAIL: workspace drill: without the access key encryption key Semaphore never ran the task, so the clone step went unproven"
        exit 1
    fi
    echo "workspace drill: without the access key encryption key the clone step fails"
    restore_env semaphore

    blank_env openbao OPENBAO_SEAL_KEY
    deadline=$(( $(date +%s) + CONTROL_WINDOW ))
    while (( $(date +%s) < deadline )); do
        if [[ "$(drill sealed)" == "false" ]]; then
            echo "FAIL: workspace drill: OpenBao unsealed without the seal key"
            exit 1
        fi
        sleep 5
    done
    echo "workspace drill: without the seal key OpenBao stays sealed for ${CONTROL_WINDOW}s"
    restore_env openbao
    deadline=$(( $(date +%s) + BKP_TEST_HEALTH_TIMEOUT ))
    until [[ "$(drill sealed)" == "false" ]]; do
        if (( $(date +%s) >= deadline )); then
            echo "FAIL: workspace drill: OpenBao stays sealed after its seal key came back"
            exit 1
        fi
        sleep 5
    done
    trap - EXIT
}

cleanup() {
    local ws kept="" left=()
    drill task "${STATE}/result-${IDS[0]}.json" "destroy-incus ws-${IDS[0]}" "${STATE}/destroy.log" || kept="${IDS[0]}"
    for ws in "${IDS[@]}"; do
        if [[ "${ws}" == "${kept}" ]]; then
            left+=("the server, repository and workspace of ${ws} for a retried destroy-incus")
            continue
        fi
        drill repository delete "${STATE}/result-${ws}.json" "provision-incus ws-${ws}" || left+=("the repository of ${ws}")
        drill workspace destroy "${ws}" "${STATE}/destroy-${ws}" || left+=("the workspace ${ws}")
    done
    if (( ${#left[@]} > 0 )); then
        echo "FAIL: workspace drill: the cleanup left behind: $(printf '%s; ' "${left[@]}")see ${STATE}"
        exit 1
    fi
    rm -rf "${STATE}"
    echo "workspace drill: removed the drill's server, repositories and workspaces"
}

case "${1:-}" in
    prepare) prepare ;;
    prove) prove "${2:?restore start epoch}" ;;
    controls) controls ;;
    cleanup) cleanup ;;
    *)
        echo "usage: pass.sh prepare|prove <epoch>|controls|cleanup" >&2
        exit 2
        ;;
esac
