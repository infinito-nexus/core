#!/bin/bash
# Param: STACK    - swarm stack of the engine (e.g. postgres)
# Param: INSTANCE - instance service key (e.g. postgres-mgr-01)
# Param: PORT     - port of the instance's own primary check, from ha.endpoint.check_port
# Param: PATH_    - path of that check, from ha.endpoint.check_path
#
# Exit codes:
#   0   the check answers 2xx: the instance is the primary or writer
#   1   the check answered with an error status: the instance is not
#   2   the instance could not be asked
#   3   the instance's service is not deployed
#   64  missing args
set -u

STACK="${1:-}"
INSTANCE="${2:-}"
PORT="${3:-}"
PATH_="${4:-}"
if [ -z "$STACK" ] || [ -z "$INSTANCE" ] || [ -z "$PORT" ] || [ -z "$PATH_" ]; then
	echo "primary-probe-http: STACK, INSTANCE, PORT and PATH required" >&2
	exit 64
fi

CID=$("$(dirname "$0")/resolve-container-id" "$STACK" "$INSTANCE" 2>/dev/null)
case "$?" in
0) ;;
67) exit 3 ;;
*) exit 2 ;;
esac

container exec "$CID" python3 -c '
import sys, urllib.error, urllib.request
try:
    urllib.request.urlopen("http://127.0.0.1:%s%s" % (sys.argv[1], sys.argv[2]), timeout=5)
except urllib.error.HTTPError:
    sys.exit(1)
except Exception:
    sys.exit(2)
' "$PORT" "$PATH_"
RC=$?
case "$RC" in
0 | 1) exit "$RC" ;;
*) exit 2 ;;
esac
