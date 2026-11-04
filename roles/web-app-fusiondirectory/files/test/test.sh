#!/usr/bin/env bash
#
# Env (rendered into test.env from templates/test.env.j2):
#   FUSIONDIRECTORY_CONTAINER         addressable FusionDirectory container
#   FUSIONDIRECTORY_IDENTITY_HEADER   header the header login reads the user name from
#   FUSIONDIRECTORY_SSO_PROXY_HEADER  header the front proxy carries its shared secret in
#   FUSIONDIRECTORY_FORGED_USER       user name a forged identity header claims
set -euo pipefail

: "${FUSIONDIRECTORY_CONTAINER:?}"
: "${FUSIONDIRECTORY_IDENTITY_HEADER:?}"
: "${FUSIONDIRECTORY_SSO_PROXY_HEADER:?}"
: "${FUSIONDIRECTORY_FORGED_USER:?}"

status() {
    container exec "${FUSIONDIRECTORY_CONTAINER}" \
        curl -s --connect-timeout 5 --max-time 30 --retry 3 --retry-all-errors --retry-delay 2 \
        -o /dev/null -w '%{http_code}' "$@" http://127.0.0.1/index.php
}

refused() {
    local label="$1"
    shift
    local got
    got="$(status "$@")"
    if [[ "${got}" != "403" ]]; then
        echo "[FAIL] ${label}: expected HTTP 403, got ${got}" >&2
        exit 1
    fi
    echo "[OK]   ${label}: HTTP ${got}"
}

control="$(status)"
if [[ "${control}" == "403" || "${control}" == "000" || -z "${control}" ]]; then
    echo "[FAIL] a request without identity header must reach FusionDirectory, got HTTP ${control}" >&2
    exit 1
fi
echo "[OK]   a request without identity header reaches FusionDirectory: HTTP ${control}"

refused "a forged identity header without the proxy secret" \
    -H "${FUSIONDIRECTORY_IDENTITY_HEADER}: ${FUSIONDIRECTORY_FORGED_USER}"
refused "a forged identity header with a guessed proxy secret" \
    -H "${FUSIONDIRECTORY_IDENTITY_HEADER}: ${FUSIONDIRECTORY_FORGED_USER}" \
    -H "${FUSIONDIRECTORY_SSO_PROXY_HEADER}: forged"

echo "ALL CHECKS PASSED"
