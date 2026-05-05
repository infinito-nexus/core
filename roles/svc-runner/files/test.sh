#!/usr/bin/env bash
# Verifies that the svc-runner role was deployed correctly on this machine.
# Run after `scripts/tests/runner.sh` completes the Ansible deploy.
set -euo pipefail

PASS=0
FAIL=0

ok()   { echo "PASS: $*"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $*"; FAIL=$((FAIL + 1)); }

RUNNER_COUNT="${RUNNER_COUNT:-1}"
RUNNER_INSTALL_DIR="${RUNNER_INSTALL_DIR:-/opt/github-runner}"

# ── System user ────────────────────────────────────────────────────────────────
if id github-runner >/dev/null 2>&1; then
    ok "github-runner system user exists"
else
    fail "github-runner system user not found"
fi

# ── Per-instance checks ────────────────────────────────────────────────────────
i=1
while [ "$i" -le "${RUNNER_COUNT}" ]; do
    DIR="${RUNNER_INSTALL_DIR}/${i}"

    if [ -f "${DIR}/run.sh" ]; then
        ok "Instance ${i}: runner binary installed (run.sh)"
    else
        fail "Instance ${i}: runner binary missing at ${DIR}/run.sh"
    fi

    if [ -f "${DIR}/.runner" ]; then
        ok "Instance ${i}: runner registered (.runner config exists)"
    else
        fail "Instance ${i}: runner not registered (.runner missing)"
    fi

    if [ -f "${DIR}/.env" ]; then
        ok "Instance ${i}: .env file exists"

        if grep -q "INFINITO_PRESERVE_DOCKER_CACHE=true" "${DIR}/.env"; then
            ok "Instance ${i}: INFINITO_PRESERVE_DOCKER_CACHE=true present in .env"
        else
            fail "Instance ${i}: INFINITO_PRESERVE_DOCKER_CACHE=true missing from .env"
        fi

        if grep -q "INFINITO_RUNNER_PREFIX=runner-${i}" "${DIR}/.env"; then
            ok "Instance ${i}: INFINITO_RUNNER_PREFIX=runner-${i} present in .env"
        else
            fail "Instance ${i}: INFINITO_RUNNER_PREFIX=runner-${i} missing from .env"
        fi

        if grep -q "INFINITO_DOCKER_VOLUME=/mnt/docker/${i}" "${DIR}/.env"; then
            ok "Instance ${i}: INFINITO_DOCKER_VOLUME=/mnt/docker/${i} present in .env"
        else
            fail "Instance ${i}: INFINITO_DOCKER_VOLUME=/mnt/docker/${i} missing from .env"
        fi
    else
        fail "Instance ${i}: .env file missing at ${DIR}/.env"
    fi

    # Systemd service — find the service unit installed by svc.sh
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

    i=$((i + 1))
done

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
