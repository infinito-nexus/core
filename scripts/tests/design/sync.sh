#!/usr/bin/env bash
# Re-render the static corporate design files of one deployed app inside the
# running stack: shared CSS, role style.css and the branding assets. No
# redeploy. Injected scripts stay as deployed, their CSP hashes live in the vhost.
#
# Param app: deployed application id (required).
# Param variant: matrix round index the app was deployed with (optional).
# Param base: hex base color that replaces the one of the inventory for this run, e.g. '#001f3f' (optional).
set -euo pipefail

: "${app:?app=<application_id> required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"
# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

inv_dir="${INFINITO_INVENTORY_DIR}${variant:+-${variant}}"

extra="{\"APPLICATIONS_WHITELIST\": [\"${app}\"], \"sync_scope\": \"design\""
if [[ -n "${base:-}" ]]; then
	extra+=", \"DESIGN_BASE_COLOR\": \"${base}\""
fi
extra+="}"

cmd="\"\${INFINITO_VENV_DIR}/bin/ansible-playbook\" -i '${inv_dir}/devices.yml' playbook-sync.yml -l localhost --vault-password-file '${inv_dir}/.password' -e '${extra}' -e ASYNC_ENABLED=false" \
	bash scripts/tests/deploy/local/exec/container.sh
