#!/usr/bin/env bash
# Args:
#   none; any argument is refused
#
# Env (survey variables of dns ws-<id>, the template and the runner):
#   DNS_ACTION                     create, remove or unlock
#   SALES_ORDER, LINE              the order line the record belongs to
#   HOST, DNS_LABEL                the address and label of create
#   WORKSPACE, WORKSPACE_DNS_ZONE,
#   WORKSPACE_DNS_ZONE_ID,
#   WORKSPACE_TARGETS              the values workspace apply wrote
#   SEMAPHORE_JWT                  the task token the OpenBao login takes, handed
#                                  to provision.py on descriptor 3, never in its
#                                  environment
#   BAO_ADDR, PROVISION_*          the settings of the provision runner
set -euo pipefail

here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
exec env -u SEMAPHORE_JWT python3 -E -s "${here}/../../python/provision.py" dns "$@" 3<<<"${SEMAPHORE_JWT-}"
