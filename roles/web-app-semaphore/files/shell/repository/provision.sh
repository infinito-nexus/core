#!/usr/bin/env bash
# Args:
#   none; any argument is refused
#
# Env (survey variables of provision ws-<id>, the template and the runner):
#   SALES_ORDER, LINE              the order line, $defs.order of interface.json
#   PROVIDER_TOKEN                 platform or workspace, $defs.provider_token
#   WORKSPACE, WORKSPACE_DNS_ZONE,
#   WORKSPACE_DNS_ZONE_ID          the values workspace apply wrote
#   SEMAPHORE_JWT                  the task token the OpenBao login takes
#   BAO_ADDR, PROVISION_*          the settings of the provision runner
set -euo pipefail

here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
exec python3 -E -s "${here}/../../python/provision.py" provision "$@"
