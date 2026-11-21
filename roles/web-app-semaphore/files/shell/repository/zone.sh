#!/usr/bin/env bash
# Args:
#   none; any argument is refused
#
# Env (survey variables of zone ws-<id>, the template and the runner):
#   ZONE_ACTION                    create, show, delete or unlock
#   SALES_ORDER, LINE              the order line the zone belongs to
#   DOMAIN                         the zone apex of create and show, unset
#                                  for delete and unlock
#   WORKSPACE, WORKSPACE_DNS_ZONE,
#   WORKSPACE_DNS_ZONE_ID          the values workspace apply wrote
#   SEMAPHORE_JWT                  the task token the OpenBao login takes, handed
#                                  to provision.py on descriptor 3, never in its
#                                  environment
#   BAO_ADDR, PROVISION_*          the settings of the provision runner
set -euo pipefail

SCRIPT="zone.sh"
here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
# shellcheck source=SCRIPTDIR/lib.sh
source "${here}/lib.sh"

refuse_arguments 0 "$@"
case "${ZONE_ACTION:-}" in
create | show)
	require DOMAIN "${ZONE_PATTERN}"
	;;
delete | unlock)
	refuse_set DOMAIN
	;;
*)
	refuse "ZONE_ACTION '${ZONE_ACTION:-}' is not one of create, show, delete, unlock"
	;;
esac
require SALES_ORDER "${SALES_ORDER_PATTERN}"
require LINE "${LINE_PATTERN}"
exec env -u SEMAPHORE_JWT python3 -E -s "${here}/../../python/provision.py" zone 3<<<"${SEMAPHORE_JWT-}"
