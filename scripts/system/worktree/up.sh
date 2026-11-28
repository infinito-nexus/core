#!/usr/bin/env bash
# shellcheck shell=bash
#
# Create an isolated git worktree for a branch and pin it to a free slot, so
# its compose stack no longer collides with the primary checkout on subnet,
# host ports, container names or volumes.
#
# Use `make worktree-up` rather than calling this script directly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# shellcheck source=scripts/system/worktree/lib.sh
source "${SCRIPT_DIR}/lib.sh"

branch="${1:?branch name required}"
base="${2:-}"

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

echo ">>> Creating worktree for '${branch}' at ${path}"
git worktree add "${path}" "${branch}"

if ! slot="$(worktree_allocate_slot "${path}")"; then
	echo "FAILURE: the slot registry gave ${path} no slot" >&2
	if git worktree remove --force "${path}"; then
		echo ">>> Removed the worktree ${path} again" >&2
	else
		echo "FAILURE: could not remove ${path}; run 'make worktree-down branch=${branch} force=true'" >&2
	fi
	exit 1
fi
echo ">>> Slot ${slot} recorded for the default stack of ${path}"

git_common_dir="$(git rev-parse --path-format=absolute --git-common-dir)"

lab_prefix="10.160.${slot}"

echo ">>> Pinning slot ${slot} in ${path}/custom.env"
cat >"${path}/custom.env" <<PINS
INFINITO_INSTANCE=${slot}
INFINITO_GIT_COMMON_DIR=${git_common_dir}
INFINITO_SUBNET=172.30.${slot}.0/24
INFINITO_GATEWAY=172.30.${slot}.1
INFINITO_DNS_IP=172.30.${slot}.53
INFINITO_IP4=172.30.${slot}.10
INFINITO_BIND_IP=127.0.0.$((slot + 1))
INFINITO_SWARM_LAB_SUBNET=${lab_prefix}.0/24
INFINITO_SWARM_MGR_IP=${lab_prefix}.10
INFINITO_SWARM_WRK1_IP=${lab_prefix}.11
INFINITO_SWARM_WRK2_IP=${lab_prefix}.12
INFINITO_SWARM_NFS_IP=${lab_prefix}.13
INFINITO_SWARM_BACKUP_IP=${lab_prefix}.14
INFINITO_RUNNER_PREFIX=infinito-${slug}
INFINITO_CONTAINER=infinito_nexus_${slug//[.-]/_}
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
	INFINITO_SWARM_LAB_SUBNET="${lab_prefix}.0/24" \
	INFINITO_SWARM_MGR_IP="${lab_prefix}.10" \
	INFINITO_SWARM_WRK1_IP="${lab_prefix}.11" \
	INFINITO_SWARM_WRK2_IP="${lab_prefix}.12" \
	INFINITO_SWARM_NFS_IP="${lab_prefix}.13" \
	INFINITO_SWARM_BACKUP_IP="${lab_prefix}.14" \
	INFINITO_RUNNER_PREFIX="infinito-${slug}" \
	python3 -m cli.meta.env

cat <<SUMMARY

Worktree ready.

  branch     ${branch}
  path       ${path}
  slot       ${slot}
  subnet     172.30.${slot}.0/24
  bind IP    127.0.0.$((slot + 1))
  container  infinito_nexus_${slug//[.-]/_}
  domain     $(awk -F= '$1 == "INFINITO_DOMAIN" { print $2 }' "${path}/.env")

Next:
  cd ${path}
  make compose-up
  make network-dns-setup   # routes the domain above to the bind IP

Release with:
  make worktree-down branch=${branch}
SUMMARY
