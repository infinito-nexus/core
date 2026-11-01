#!/usr/bin/env bash
# Param: BIN_RESOLVE_CONTAINER_ID (env) - path of the resolve-container-id helper
# Param: $1     - swarm stack name
# Param: $2     - service key of the local MariaDB or OpenLDAP instance that runs the probe
# Param: $3...  - writer URLs of every elector; exits 0 when exactly one answers
set -euo pipefail
stack="${1:?stack name required}"
service_key="${2:?service key required}"
shift 2
container exec "$("${BIN_RESOLVE_CONTAINER_ID:?resolver path required}" "$stack" "$service_key")" python3 -c '
import sys, urllib.request
up = []
for url in sys.argv[1:]:
    try:
        urllib.request.urlopen(url, timeout=2)
        up.append(url)
    except Exception:
        pass
print(f"writers={len(up)} {up}")
sys.exit(0 if len(up) == 1 else 1)
' "$@"
