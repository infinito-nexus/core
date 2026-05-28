#!/usr/bin/env bash
# Deploy on performance hardware — deploy the full set of applications.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/tests/environment/utils/common.sh
source "${SCRIPT_DIR}/utils/common.sh"

echo "Deploying matomo (full cycle: deploy + update pass) so it becomes reachable via its dedicated inventory entry."
make compose-deploy mode=reinstall apps="${MATOMO_APP}" full_cycle=true
inspect

echo "Re-trusting the CA after the fresh deploy rebuilt the certificates."
make network-trust-ca

echo "Verifying matomo is now reachable after its dedicated deploy."
assert_http_status 200 "${MATOMO_URL}"

echo "Verifying the dashboard is no longer reachable after the matomo-only fresh deploy."
# Expect 000 because curl aborts in TLS before HTTP when the removed hostname is missing from the certificate SANs.
assert_http_status 000 "${DASHBOARD_URL}"
