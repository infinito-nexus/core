#!/usr/bin/env bash
# Param role: deployed application id (required).
# Param variant: matrix round index the app was deployed with (optional).
# Param pw: Playwright arguments, split the way a shell splits words and handed over as the list TEST_E2E_PLAYWRIGHT_ARGUMENTS of the extra vars, which one json.dumps call writes with every parameter; when set, the spec of the role is staged again, its .env rendered again and run with them (optional).
# Param keep: true lets that spec run capture the design gallery (optional).
# Param base: hex base color that replaces the one of the inventory for this run, e.g. '#001f3f' (optional).
# Param task: task file of the role, relative to its tasks directory, that runs alone instead of the whole role, e.g. 06_design.yml (optional). It gets the variables of the role and nothing an earlier task of the role would have set.
set -euo pipefail

: "${role:?role=<application_id> required}"

scope="role"
if [[ -n "${task:-}" ]]; then
	[[ "${task}" =~ ^[A-Za-z0-9_./-]+$ ]] || {
		echo "task must be a task file path of the role: ${task}" >&2
		exit 2
	}
	scope="task"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
cd "${REPO_ROOT}"
# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

inv_dir="${INFINITO_INVENTORY_DIR}${variant:+-${variant}}"

extra="$(python3 -c '
import json, shlex, sys
role, scope, task, base, pw, keep = sys.argv[1:]
extra = {"APPLICATIONS_WHITELIST": [role], "sync_scope": scope, "sync_task": task}
if base:
    extra["DESIGN_BASE_COLOR"] = base
if pw:
    extra["sync_playwright"] = True
    extra["TEST_E2E_PLAYWRIGHT_ARGUMENTS"] = shlex.split(pw)
    extra["test_e2e_playwright_keep"] = keep
print(json.dumps(extra))
' "${role}" "${scope}" "${task:-}" "${base:-}" "${pw:-}" "${keep:-false}")"
printf -v extra_word '%q' "${extra}"

cmd="\"\${INFINITO_VENV_DIR}/bin/ansible-playbook\" -i '${inv_dir}/devices.yml' playbook-sync.yml -l localhost --vault-password-file '${inv_dir}/.password' -e ${extra_word}" \
	bash scripts/tests/deploy/local/exec/container.sh
