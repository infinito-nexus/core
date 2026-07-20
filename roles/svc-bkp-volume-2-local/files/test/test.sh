#!/usr/bin/env bash
set -euo pipefail

: "${ASYNC_ENABLED:?}"
: "${BKP_TEST_IS_STACK_HOST:?}"
: "${BKP_TEST_BACKUPS_DIR:?}"
: "${BKP_TEST_SERVICE:?}"
: "${BKP_TEST_RESTORE_BIN:?}"
: "${BKP_TEST_HEALTH_TIMEOUT:?}"
: "${BKP_TEST_SWARM_DRILL:?}"

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
                journalctl -u "${BKP_TEST_SERVICE}" --no-pager -n 100 2>&1 || true
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

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SWARM_ACTIVE=false
if [[ "$(container info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null)" == "active" ]]; then
    SWARM_ACTIVE=true
fi

MACHINE_HASH="$(sha256sum /etc/machine-id | cut -c1-64)"
HANDOFF_PENDING="${DIR}/swarm-restore.pending"
HANDOFF_COMPLETE="${DIR}/swarm-restore.complete"
HANDOFF_MANIFEST="${DIR}/swarm-restore.manifest"

if [[ "${ASYNC_ENABLED}" != "true" ]] && [[ "${SWARM_ACTIVE}" == "true" ]]; then
    if [[ "${BKP_TEST_SWARM_DRILL}" != "true" ]]; then
        echo "FAIL: refusing to replay database dumps on an active Swarm outside the orchestrated CI DR drill"
        exit 1
    fi
    rm -f "${HANDOFF_PENDING}" "${HANDOFF_COMPLETE}" "${HANDOFF_MANIFEST}"
    PROBE_BASE="infinito_${MACHINE_HASH:0:12}_$(date +%s)_${BASHPID}"
    PROBE_PRE_TOKEN="${PROBE_BASE}_pre"
    PROBE_POST_TOKEN="${PROBE_BASE}_post"
    bash "${DIR}/db_probe.sh" seed "${PROBE_PRE_TOKEN}"
fi

echo "Forcing a post-deploy backup run (the service-loader pre-state backup can predate the app volumes and be empty)"
if ! timeout "${BKP_TEST_HEALTH_TIMEOUT}" systemctl start "${BKP_TEST_SERVICE}"; then
    echo "backup unit start returned non-zero; inspecting result"
fi
wait_service_terminated

MACHINE_DIR="${BKP_TEST_BACKUPS_DIR%/}/${MACHINE_HASH}"

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

export MACHINE_HASH REPO_DIR REPO_NAME

if [[ "${ASYNC_ENABLED}" == "true" ]]; then
    if (( COUNT < 2 )); then
        echo "Only ${COUNT} generation(s); triggering one extra backup run for differential coverage"
        if ! timeout "${BKP_TEST_HEALTH_TIMEOUT}" systemctl start "${BKP_TEST_SERVICE}"; then
            echo "backup unit start returned non-zero; inspecting result"
        fi
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

if [[ "${SWARM_ACTIVE}" == "true" ]]; then
    mapfile -t SQL_FILES < <(find "${REPO_DIR}/${NEWEST_GENERATION}" -mindepth 3 -maxdepth 3 \
        -type f -path '*/sql/*.backup.sql' ! -name '*.cluster.backup.sql' | sort)
    if (( ${#SQL_FILES[@]} < 1 )); then
        echo "SWARM SYNC PASS COMPLETE: backup verified; no single-database dumps require a restore"
        exit 0
    fi

    bash "${DIR}/db_probe.sh" seed "${PROBE_POST_TOKEN}"
    umask 077
    {
        printf 'MACHINE_HASH=%q\n' "${MACHINE_HASH}"
        printf 'REPO_NAME=%q\n' "${REPO_NAME}"
        printf 'NEWEST_GENERATION=%q\n' "${NEWEST_GENERATION}"
        printf 'PROBE_PRE_TOKEN=%q\n' "${PROBE_PRE_TOKEN}"
        printf 'PROBE_POST_TOKEN=%q\n' "${PROBE_POST_TOKEN}"
    } >"${HANDOFF_PENDING}.tmp"
    mv "${HANDOFF_PENDING}.tmp" "${HANDOFF_PENDING}"
    echo "SWARM SYNC PASS COMPLETE: destructive database restore handed to the orchestrated CI DR drill"
    exit 0
fi

bash "${DIR}/restore_cycle.sh"
bash "${DIR}/db_restore.sh"
echo "SYNC PASS COMPLETE: backup verified and restore cycle succeeded"
