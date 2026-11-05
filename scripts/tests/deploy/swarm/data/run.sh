#!/usr/bin/env bash
# Param:
#   engine                       postgres | mariadb | redis | openldap
#   FAILOVER_JUNIT               JUnit output file
#   SWARM_NAME                   optional cluster id (default data-<engine>)
#   INFINITO_KEEP_SWARM_NODES    true keeps the lab for inspection
#   FAILOVER_ONLY                optional space-separated scenario names to run
#   disable                      services kept out of the lab (default tor)
#   SWARM_DATA_REUSE             true reruns the suite on the kept lab of an earlier run,
#                                skipping bring-up and deploys
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
	exec sudo --preserve-env="$(compgen -e | paste -sd, -)" env "PATH=$PATH" "HOME=$HOME" bash "$0" "$@"
fi

: "${engine:?engine=<postgres|mariadb|redis|openldap> is required}"
: "${FAILOVER_JUNIT:?FAILOVER_JUNIT is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
cd "${REPO_ROOT}"

export APP_ID="svc-db-${engine}"
export SWARM_NAME="${SWARM_NAME:-data-${engine}}"
export INFINITO_SWARM_DB_TOPOLOGY=ha
export SWARM_DATA_FORM=ha
export SWARM_LAB_CONSUMER=lightest
export disable="${disable:-tor}"
RUNNER_TEMP="${RUNNER_TEMP:-$(mktemp -d)}"
export RUNNER_TEMP

set -a
# shellcheck source=scripts/tests/deploy/swarm/utils/topology/base.sh
. "${REPO_ROOT}/scripts/tests/deploy/swarm/utils/topology/base.sh"
set +a

# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

inv_base="${INFINITO_INVENTORY_DIR:-/tmp/inv}" # nocheck: swarm-test base (the matrix writes <base>-<round> per round; /tmp/inv standalone)
kept_inventory="/root/failover-inventory.tar"
stack_node="${SWARM_LAB_MANAGERS%% *}"

save_inventory() {
	local file
	file="$(find "$(dirname "${inv_base}")" -maxdepth 2 -path "${inv_base}*/devices.yml" | sort -V | tail -1)"
	[ -n "${file}" ] || return 0
	tar -C "$(dirname "${file}")" -cf - . | docker exec -i "${stack_node}" sh -c "cat > ${kept_inventory}"
}

teardown() {
	save_inventory || true                                                         # nocheck: shell-or-true -- best-effort save in the EXIT trap
	bash "${REPO_ROOT}/scripts/tests/deploy/swarm/utils/clean/teardown.sh" || true # nocheck: shell-or-true -- best-effort teardown in the EXIT trap
}
trap teardown EXIT

SWARM_DATA_LAB_VARS="${RUNNER_TEMP}/failover-lab-sizes.yml"
export SWARM_DATA_LAB_VARS
python3 -m utils.failover lab-overrides --out "${SWARM_DATA_LAB_VARS}"

if [ "${SWARM_DATA_REUSE:-false}" = "true" ]; then
	echo "==> reusing the kept lab of an earlier run"
	mkdir -p "${inv_base}-kept"
	docker exec "${stack_node}" cat "${kept_inventory}" | tar -C "${inv_base}-kept" -xf -
else
	bash "${REPO_ROOT}/scripts/tests/deploy/swarm/routine/01_bootstrap.sh"

	echo "==> lab memory per node after bring-up"
	# shellcheck disable=SC2086  # the lab node list is space-separated words
	docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' ${SWARM_LAB_NODES}

	python3 -m utils.tests.swarm.matrix

	echo "==> lab memory per node after the engine deploy"
	# shellcheck disable=SC2086  # the lab node list is space-separated words
	docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' ${SWARM_LAB_NODES}
fi

inv_file="$(find "$(dirname "${inv_base}")" -maxdepth 2 -path "${inv_base}*/devices.yml" | sort -V | tail -1)"
: "${inv_file:?no devices.yml provisioned under the swarm-test inventory}"
inv_dir="$(dirname "${inv_file}")"
ansible-playbook \
	-i "${inv_file}" \
	--vault-password-file "${inv_dir}/.password" \
	-e "@${inv_dir}/swarm-nfs-extras.deploy.yml" \
	-e "engine=${engine}" \
	"${REPO_ROOT}/playbooks/failover-checker.yml"

read -ra only_args <<<"${FAILOVER_ONLY:-}"
python3 -m utils.failover run --engine "${engine}" --junit "${FAILOVER_JUNIT}" ${FAILOVER_ONLY:+--only "${only_args[@]}"}
