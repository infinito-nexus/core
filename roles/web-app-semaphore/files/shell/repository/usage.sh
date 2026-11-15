#!/usr/bin/env bash
# Env (the environment workspace apply wrote; the template takes no survey):
#   WORKSPACE                 the workspace id, a lowercase UUID
#   WORKSPACE_TARGETS         comma-separated <host>:<port> pairs apply pinned
#   WORKSPACE_INVENTORY_FILE  the inventory file of the checkout
#   INFINITO_SRC_DIR          the core tree of the runner image
set -euo pipefail

SCRIPT="usage.sh"
# shellcheck source=SCRIPTDIR/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

refuse_arguments 0 "$@"
require WORKSPACE "${WORKSPACE_PATTERN}"
require WORKSPACE_TARGETS '^[^[:space:]]+$'
mapfile -t hosts < <(target_hosts | sort -u)
limit="$(
	IFS=','
	printf '%s' "${hosts[*]}"
)"
inventory="$(workspace_inventory "${WORKSPACE_INVENTORY_FILE:?the environment names no inventory file}")"
guard_workspace_inventory "${inventory}"

workdir="$(mktemp -d)"
trap 'rm -rf "${workdir}"' EXIT
install -d -m 0700 "${workdir}/hosts"
python3 -c 'import json, sys
json.dump({"ansible_connection": "local", "usage_result_dir": sys.argv[1]}, sys.stdout)' \
	"${workdir}/hosts" >"${workdir}/operation.json"
counted_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "${SCRIPT}: counting the active people on ${limit}"
(
	cd "${INFINITO_SRC_DIR:?the runner image names no core tree}"
	ansible-playbook -i "${inventory}" playbook-usage.yml --limit "${limit}" -e "@${workdir}/operation.json"
)
python3 -c 'import json, os, sys
workspace, counted_at, directory = sys.argv[1:]
hosts = []
for name in sorted(os.listdir(directory)):
    with open(os.path.join(directory, name), encoding="utf-8") as handle:
        entry = json.load(handle)
    users = entry.get("active_users") if isinstance(entry, dict) else -1
    if (
        not isinstance(entry, dict)
        or set(entry) != {"host", "realm", "active_users"}
        or not (users is None or (type(users) is int and users >= 0))
    ):
        raise SystemExit(f"usage.sh: {name} holds no count")
    hosts.append(entry)
print(json.dumps({"workspace": workspace, "counted_at": counted_at, "hosts": hosts}, sort_keys=True))' \
	"${WORKSPACE}" "${counted_at}" "${workdir}/hosts"
