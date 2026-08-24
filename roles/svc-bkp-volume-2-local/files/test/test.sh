#!/usr/bin/env bash
# E2E orchestrator for svc-bkp-volume-2-local.
# Runs once, in the sync pass: wait for the backup service to terminate, back
# up, seed a marker and back up again so the tested generation carries it, take
# every project down, restore through the recover chain, require the marker
# back and every recorded container up, then let the host's own container
# health service pass judgement. The health script is run directly rather than
# through its unit: the unit's OnFailure would start the soft-repair service
# and the drill would heal what it is supposed to report.
# The restore half is compose-only, because tearing a swarm stack down races
# the orchestrator; there the token is cleaned up again and
# scripts/tests/deploy/swarm/routine/backup drills the recovery instead.
# Variables sourced from test.env.j2 by test-e2e-cli.
set -euo pipefail

: "${ASYNC_ENABLED:?}"
: "${BKP_TEST_IS_STACK_HOST:?}"
: "${BKP_TEST_BACKUPS_DIR:?}"
: "${BKP_TEST_SERVICE:?}"
: "${BKP_TEST_HEALTH_SCRIPT:?}"
: "${BKP_TEST_HEALTH_TIMEOUT:?}"
: "${BKP_TEST_PYTHON:?}"

if [[ "${BKP_TEST_IS_STACK_HOST}" != "true" ]]; then
    echo "SKIP: not the stack host; svc-bkp-volume-2-local only deploys there"
    exit 0
fi

if [[ "${ASYNC_ENABLED}" == "true" ]]; then
    echo "SKIP: the drill runs once, in the sync pass; repeating it here would tear the host down a second time for the same answer"
    exit 0
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "${DIR}/probe/subvolume.sh"
bash "${DIR}/probe/snapshot.sh"

# Param $1: when non-empty, a unit already sitting in 'failed' is a verdict
#           from an earlier deploy rather than this run's, so clear it and
#           carry on instead of reporting a backup this drill never started.
wait_service_terminated() {
    local stale_failure_ok="${1:-}"
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
                if [ -n "${stale_failure_ok}" ]; then
                    echo "OK: clearing a 'failed' state left by an earlier run"
                    systemctl reset-failed "${BKP_TEST_SERVICE}"
                    return 0
                fi
                echo "FAIL: ${BKP_TEST_SERVICE} terminated in state 'failed'"
                systemctl status "${BKP_TEST_SERVICE}" --no-pager 2>&1 | tail -20
                journalctl -u "${BKP_TEST_SERVICE}" --no-pager -n 100 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
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

wait_service_terminated stale_failure_ok

echo "Forcing a post-deploy backup run (the service-loader pre-state backup can predate the app volumes and be empty)"
if ! timeout "${BKP_TEST_HEALTH_TIMEOUT}" systemctl start "${BKP_TEST_SERVICE}"; then
    echo "backup unit start returned non-zero; inspecting result"
fi
wait_service_terminated

MACHINE_HASH="$(sha256sum /etc/machine-id | cut -c1-64)"
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

VOLUME_COUNT="$(container volume ls -q | wc -l)"
COMPOSE_CONTAINERS="$(container ps -q --filter label=com.docker.compose.project | wc -l)"
if (( VOLUME_COUNT == 0 && COMPOSE_CONTAINERS == 0 )); then
    NEWEST="${GENERATIONS[-1]}"
    PAYLOAD="$(find "${REPO_DIR}/${NEWEST}" -mindepth 2 -maxdepth 2 -type d \( -name files -o -name sql \) | wc -l)"
    if (( PAYLOAD > 0 )); then
        echo "FAIL: host reports no backup subjects but generation ${NEWEST} contains ${PAYLOAD} payload dir(s)"
        exit 1
    fi
    echo "OK/SKIP: no backup subjects on this host; the stamped empty generation ${NEWEST} is the expected outcome"
    exit 0
fi

export MACHINE_HASH REPO_DIR REPO_NAME

export NEWEST_GENERATION="${GENERATIONS[-1]}"
bash "${DIR}/verify/backup.sh"

DR_TOKEN="dr-$(date +%s)-$$"
SEEDED_GENERATION="${REPO_DIR}/${NEWEST_GENERATION}"
export DR_TOKEN
"${BKP_TEST_PYTHON}" "${DIR}/seed/marker.py" seed "${SEEDED_GENERATION}" "${DR_TOKEN}"
trap '"${BKP_TEST_PYTHON}" "${DIR}/seed/marker.py" clean "${REPO_DIR}/${NEWEST_GENERATION}" "${DR_TOKEN}"' EXIT

echo "Backing up once more so the generation under test carries the marker"
if ! timeout "${BKP_TEST_HEALTH_TIMEOUT}" systemctl start "${BKP_TEST_SERVICE}"; then
    echo "backup unit start returned non-zero; inspecting result"
fi
wait_service_terminated
count_generations
export NEWEST_GENERATION="${GENERATIONS[-1]}"

subjects() {
    find "$1" -mindepth 2 -maxdepth 2 -type d \( -name files -o -name sql \) -printf '%h\n' |
        xargs -rn1 basename | sort -u
}
if ! diff <(subjects "${SEEDED_GENERATION}") <(subjects "${REPO_DIR}/${NEWEST_GENERATION}"); then
    echo "FAIL: the generation under test covers different subjects than the one the marker was seeded from; the drill would prove only their intersection"
    exit 1
fi

"${BKP_TEST_PYTHON}" "${DIR}/seed/marker.py" captured "${REPO_DIR}/${NEWEST_GENERATION}" "${DR_TOKEN}"

if [[ "$(container info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null)" == "active" ]]; then
    echo "SKIP: swarm node; the restore half needs compose lifecycle control, so it is drilled by scripts/tests/deploy/swarm/routine/backup"
    echo "SYNC PASS COMPLETE: backup verified and proven to carry the live payload"
    exit 0
fi

bash "${DIR}/restore_cycle.sh"

echo "Asking the host's own container health service for the verdict"
if ! bash "${BKP_TEST_HEALTH_SCRIPT}"; then
    echo "FAIL: ${BKP_TEST_HEALTH_SCRIPT} reports the host unhealthy after the restore"
    exit 1
fi

echo "SYNC PASS COMPLETE: backup verified, restore cycle succeeded, marker survived, host healthy"
