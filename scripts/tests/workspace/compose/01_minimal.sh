#!/usr/bin/env bash
# Deploy on minimal hardware — disable non-essential services to save resources.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/tests/workspace/utils/common.sh
source "${SCRIPT_DIR}/../utils/common.sh"
# shellcheck source=scripts/tests/workspace/utils/cache.sh
source "${SCRIPT_DIR}/../utils/cache.sh"

echo "Snapshotting cache counters before the deploy."
CACHE_BEFORE="$(cache_snapshot)"

echo "Deploying dashboard with all variable (group-conditional) services disabled, except the asset provider, to speed up the deploy and verify disable= suppresses them from the inventory."
# Exception: without the asset provider the dashboard loads its logo from the public file.infinito.nexus, which ties this test to that host's uptime; variant 1 pins the provider off, so only round 0 runs here.
make compose-deploy mode=reinstall apps="${DASHBOARD_APP}" variant=0 disable="$(variable_services dashboard javascript asset)"
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

dashboard_url="$(stack_url dashboard)"
matomo_url="$(stack_url matomo)"

echo "Verifying the dashboard is reachable (matomo was disabled, not the dashboard itself)."
assert_http_status 200 "${dashboard_url}"

echo "Verifying matomo is not reachable because it was excluded from the inventory."
assert_http_status 000 "${matomo_url}"
