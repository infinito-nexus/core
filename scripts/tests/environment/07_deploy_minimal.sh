#!/usr/bin/env bash
# Deploy on minimal hardware — disable non-essential services to save resources.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/tests/environment/utils/common.sh
source "${SCRIPT_DIR}/utils/common.sh"
# shellcheck source=scripts/tests/environment/utils/cache.sh
source "${SCRIPT_DIR}/utils/cache.sh"

echo "Snapshotting cache counters before the deploy."
CACHE_BEFORE="$(cache_snapshot)"

echo "Deploying dashboard with matomo disabled to verify the disable= make arg suppresses the shared service in the inventory."
make compose-deploy mode=reinstall apps="${DASHBOARD_APP}" disable="matomo"
inspect

echo "Actively probing both caches to confirm pull-through works end-to-end."
probe_caches

echo "Probing the DiD inner-build cache path (frontend hijack + apt rewrite)."
probe_did_inner_build

echo "Verifying that BOTH local caches saw real pull-through traffic."
CACHE_AFTER="$(cache_snapshot)"
assert_caches_used "${CACHE_BEFORE}" "${CACHE_AFTER}"

echo "Trusting the local CA certificate so HTTPS endpoints are reachable from the host."
make network-trust-ca

echo "Verifying the dashboard is reachable (matomo was disabled, not the dashboard itself)."
assert_http_status 200 "${DASHBOARD_URL}"

echo "Verifying matomo is not reachable because it was excluded from the inventory."
# Expect 000 because curl aborts in TLS before HTTP when the excluded hostname is missing from the certificate SANs.
assert_http_status 000 "${MATOMO_URL}"
