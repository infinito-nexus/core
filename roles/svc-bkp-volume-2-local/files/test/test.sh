#!/usr/bin/env bash
# E2E orchestrator for svc-bkp-volume-2-local.
# Waits for the backup service to terminate, then:
#   sync pass (ASYNC_ENABLED=false): verify the first backup generation is
#     stored, then run the destructive restore drill (stop containers, wipe
#     the backed-up volumes, restore, require everything healthy again) and
#     replay the sql dumps.
#   async pass (ASYNC_ENABLED=true): require two differential backup
#     generations, triggering one extra service run when only one exists;
#     no destructive steps.
# Variables sourced from test.env.j2 by test-e2e-cli.
set -euo pipefail

: "${ASYNC_ENABLED:?}"
: "${BKP_TEST_IS_STACK_HOST:?}"
: "${BKP_TEST_BACKUPS_DIR:?}"
: "${BKP_TEST_SERVICE:?}"
: "${BKP_TEST_RESTORE_BIN:?}"
: "${BKP_TEST_RSYNC_IMAGE:?}"
: "${BKP_TEST_HEALTH_TIMEOUT:?}"

if [[ "${BKP_TEST_IS_STACK_HOST}" != "true" ]]; then
    echo "SKIP: not the stack host; svc-bkp-volume-2-local only deploys there"
    exit 0
fi

wait_service_terminated() {
    local deadline state
    deadline=$(( $(date +%s) + BKP_TEST_HEALTH_TIMEOUT ))
    while :; do
        state="$(systemctl is-active "${BKP_TEST_SERVICE}" 2>/dev/null || true)"
        case "${state}" in
            active | activating | deactivating)
                if (( $(date +%s) >= deadline )); then
                    echo "FAIL: ${BKP_TEST_SERVICE} still ${state} after ${BKP_TEST_HEALTH_TIMEOUT}s"
                    exit 1
                fi
                sleep 5
                ;;
            failed)
                echo "FAIL: ${BKP_TEST_SERVICE} terminated in state 'failed'"
                systemctl status "${BKP_TEST_SERVICE}" --no-pager 2>&1 | tail -20
                exit 1
                ;;
            *)
                echo "OK: ${BKP_TEST_SERVICE} terminated (${state})"
                return 0
                ;;
        esac
    done
}

count_generations() {
    mapfile -t GENERATIONS < <(find "${REPO_DIR}" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
    COUNT="${#GENERATIONS[@]}"
}

wait_service_terminated

MACHINE_HASH="$(sha256sum /etc/machine-id | cut -c1-64)"
MACHINE_DIR="${BKP_TEST_BACKUPS_DIR%/}/${MACHINE_HASH}"

if [[ ! -d "${MACHINE_DIR}" ]]; then
    echo "No backup dir yet at ${MACHINE_DIR}; triggering an initial backup run"
    systemctl start "${BKP_TEST_SERVICE}"
    wait_service_terminated
fi
if [[ ! -d "${MACHINE_DIR}" ]]; then
    echo "FAIL: no backup dir for this machine at ${MACHINE_DIR}"
    exit 1
fi

REPO_DIR="$(find "${MACHINE_DIR}" -mindepth 1 -maxdepth 1 -type d | sort | head -n1)"
if [[ -z "${REPO_DIR}" ]]; then
    echo "FAIL: no backup repo dir under ${MACHINE_DIR}"
    exit 1
fi
REPO_NAME="$(basename "${REPO_DIR}")"

count_generations
echo "OK: backup repo '${REPO_NAME}' holds ${COUNT} generation(s)"

if (( COUNT < 1 )); then
    echo "FAIL: no backup generation stored after deploy"
    exit 1
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export MACHINE_HASH REPO_DIR REPO_NAME

if [[ "${ASYNC_ENABLED}" == "true" ]]; then
    if (( COUNT < 2 )); then
        echo "Only ${COUNT} generation(s); triggering one extra backup run for differential coverage"
        systemctl start "${BKP_TEST_SERVICE}"
        wait_service_terminated
        count_generations
    fi
    if (( COUNT < 2 )); then
        echo "FAIL: async pass expects at least 2 differential backup generations, found ${COUNT}"
        exit 1
    fi
    export NEWEST_GENERATION="${GENERATIONS[-1]}"
    export PREVIOUS_GENERATION="${GENERATIONS[-2]}"
    bash "${DIR}/verify_backup.sh"
    echo "ASYNC PASS COMPLETE: ${COUNT} differential backup generations verified"
    exit 0
fi

export NEWEST_GENERATION="${GENERATIONS[-1]}"
bash "${DIR}/verify_backup.sh"
bash "${DIR}/restore_cycle.sh"
bash "${DIR}/db_restore.sh"
echo "SYNC PASS COMPLETE: backup verified and restore cycle succeeded"
