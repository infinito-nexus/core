#!/usr/bin/env bash
# shellcheck shell=bash
#
# Create an isolated git worktree for a branch and pin it to a free slot, so
# its compose stack no longer collides with the primary checkout on subnet,
# host ports, container names or volumes. The cache stack is not duplicated:
# the worktree joins the running one over an external network.
#
# Use `make worktree-up` rather than calling this script directly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# shellcheck source=scripts/system/worktree/lib.sh
source "${SCRIPT_DIR}/lib.sh"

branch="${1:?branch name required}"
base="${2:-}"
max_slot=255

cd "${REPO_ROOT}"

base="${base:-$(worktree_default_base)}"

slug="$(worktree_slug "${branch}")"
if [ -z "${slug}" ]; then
	echo "FAILURE: branch '${branch}' slugs to an empty name" >&2
	exit 1
fi

path="$(worktree_path "${branch}" "${base}")"
mkdir -p "$(dirname "${path}")"
if [ -e "${path}" ]; then
	echo "FAILURE: ${path} already exists; run 'make worktree-down branch=${branch}' first" >&2
	exit 1
fi

slot="$(worktree_next_slot)"
if [ "${slot}" -gt "${max_slot}" ]; then
	echo "FAILURE: no free slot left (max ${max_slot}); tear down an existing worktree" >&2
	exit 1
fi

cache_network="$(worktree_cache_network)"
if [ -z "${cache_network}" ]; then
	echo ">>> WARNING: no running cache stack found; the worktree will start without a shared cache"
fi

echo ">>> Creating worktree for '${branch}' at ${path} (slot ${slot})"
git worktree add "${path}" "${branch}"

git_common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"

lab_octet="$((244 + slot))"

echo ">>> Pinning slot ${slot} in ${path}/custom.env"
cat >"${path}/custom.env" <<PINS
INFINITO_INSTANCE=${slot}
INFINITO_GIT_COMMON_DIR=${git_common_dir}
INFINITO_SUBNET=172.30.${slot}.0/24
INFINITO_GATEWAY=172.30.${slot}.1
INFINITO_DNS_IP=172.30.${slot}.53
INFINITO_IP4=172.30.${slot}.10
INFINITO_BIND_IP=127.0.0.$((slot + 1))
INFINITO_SWARM_LAB_SUBNET=192.168.${lab_octet}.0/24
INFINITO_SWARM_MGR_IP=192.168.${lab_octet}.10
INFINITO_SWARM_WRK1_IP=192.168.${lab_octet}.11
INFINITO_SWARM_WRK2_IP=192.168.${lab_octet}.12
INFINITO_SWARM_NFS_IP=192.168.${lab_octet}.13
INFINITO_SWARM_BACKUP_IP=192.168.${lab_octet}.14
INFINITO_RUNNER_PREFIX=infinito-${slug}
INFINITO_CONTAINER=infinito_nexus_${slug//[.-]/_}
INFINITO_CACHE_NETWORK=${cache_network}
PINS

echo ">>> Generating .env from the pins"
env -i -C "${path}" \
	HOME="${HOME}" \
	PATH="${PATH}" \
	INFINITO_INSTANCE="${slot}" \
	INFINITO_GIT_COMMON_DIR="${git_common_dir}" \
	INFINITO_SUBNET="172.30.${slot}.0/24" \
	INFINITO_GATEWAY="172.30.${slot}.1" \
	INFINITO_DNS_IP="172.30.${slot}.53" \
	INFINITO_IP4="172.30.${slot}.10" \
	INFINITO_BIND_IP="127.0.0.$((slot + 1))" \
	INFINITO_SWARM_LAB_SUBNET="192.168.${lab_octet}.0/24" \
	INFINITO_SWARM_MGR_IP="192.168.${lab_octet}.10" \
	INFINITO_SWARM_WRK1_IP="192.168.${lab_octet}.11" \
	INFINITO_SWARM_WRK2_IP="192.168.${lab_octet}.12" \
	INFINITO_SWARM_NFS_IP="192.168.${lab_octet}.13" \
	INFINITO_SWARM_BACKUP_IP="192.168.${lab_octet}.14" \
	INFINITO_RUNNER_PREFIX="infinito-${slug}" \
	INFINITO_CACHE_NETWORK="${cache_network}" \
	python3 -m cli.meta.env

cat <<SUMMARY

Worktree ready.

  branch     ${branch}
  path       ${path}
  slot       ${slot}
  subnet     172.30.${slot}.0/24
  bind IP    127.0.0.$((slot + 1))
  container  infinito_nexus_${slug//[.-]/_}
  cache net  ${cache_network:-<none>}

Next:
  cd ${path}
  make compose-up

Release with:
  make worktree-down branch=${branch}
SUMMARY
