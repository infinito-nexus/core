#!/usr/bin/env bash
# Verifies that the svc-runner role was deployed correctly on this machine.
# Variables are sourced from roles/svc-runner/templates/test.env.j2 by test-e2e-cli.
set -euo pipefail

PASS=0
FAIL=0

ok()   { echo "PASS: $*"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $*"; FAIL=$((FAIL + 1)); }

: "${RUNNER_COUNT:?}"
: "${RUNNER_INSTALL_DIR:?}"
: "${RUNNER_DOCKER_BASE:?}"
: "${RUNNER_PROJECT_PREFIX:?}"
: "${RUNNER_USER:?}"
: "${DOCKER_IN_CONTAINER:?}"

# Skip gracefully when svc-runner was never deployed on this host
if ! id "${RUNNER_USER}" >/dev/null 2>&1; then
    echo "SKIP: ${RUNNER_USER} user absent — svc-runner not deployed on this host"
    exit 0
fi

# ── System user ────────────────────────────────────────────────────────────────
ok "${RUNNER_USER} system user exists"

# ── Per-instance checks ────────────────────────────────────────────────────────
i=1
while [ "$i" -le "${RUNNER_COUNT}" ]; do
    DIR="${RUNNER_INSTALL_DIR}/${i}"

    if [ -f "${DIR}/run.sh" ]; then
        ok "Instance ${i}: runner binary installed (run.sh)"
    else
        fail "Instance ${i}: runner binary missing at ${DIR}/run.sh"
    fi

    # .runner is created by config.sh --token; skipped in DinD (no GitHub registration)
    if [ "${DOCKER_IN_CONTAINER}" != "true" ]; then
        if [ -f "${DIR}/.runner" ]; then
            ok "Instance ${i}: runner registered (.runner config exists)"
        else
            fail "Instance ${i}: runner not registered (.runner missing)"
        fi
    fi

    if [ -f "${DIR}/.env" ]; then
        ok "Instance ${i}: .env file exists"

        if grep -q "INFINITO_PRESERVE_DOCKER_CACHE=true" "${DIR}/.env"; then
            ok "Instance ${i}: INFINITO_PRESERVE_DOCKER_CACHE=true present in .env"
        else
            fail "Instance ${i}: INFINITO_PRESERVE_DOCKER_CACHE=true missing from .env"
        fi

        if grep -q "INFINITO_RUNNER_PREFIX=${RUNNER_PROJECT_PREFIX}-${i}" "${DIR}/.env"; then
            ok "Instance ${i}: INFINITO_RUNNER_PREFIX=${RUNNER_PROJECT_PREFIX}-${i} present in .env"
        else
            fail "Instance ${i}: INFINITO_RUNNER_PREFIX=${RUNNER_PROJECT_PREFIX}-${i} missing from .env"
        fi

        if grep -q "INFINITO_DOCKER_VOLUME=${RUNNER_DOCKER_BASE}/${i}" "${DIR}/.env"; then
            ok "Instance ${i}: INFINITO_DOCKER_VOLUME=${RUNNER_DOCKER_BASE}/${i} present in .env"
        else
            fail "Instance ${i}: INFINITO_DOCKER_VOLUME=${RUNNER_DOCKER_BASE}/${i} missing from .env"
        fi
    else
        fail "Instance ${i}: .env file missing at ${DIR}/.env"
    fi

    # Systemd service — svc.sh install/start require systemd; skipped in DinD
    if [ "${DOCKER_IN_CONTAINER}" != "true" ]; then
        svc_file=$(find /etc/systemd/system -maxdepth 1 -name "actions.runner.*-${i}.service" 2>/dev/null | head -1 || true)
        if [ -n "${svc_file}" ]; then
            svc_name=$(basename "${svc_file}")
            if systemctl is-active --quiet "${svc_name}"; then
                ok "Instance ${i}: systemd service ${svc_name} is active"
            else
                fail "Instance ${i}: systemd service ${svc_name} is not active"
            fi
        else
            fail "Instance ${i}: no systemd service unit found for instance ${i}"
        fi
    fi

    i=$((i + 1))
done

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
