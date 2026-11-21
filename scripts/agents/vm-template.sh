#!/usr/bin/env bash
set -euo pipefail

# Inputs (env, set by the Makefile from make vars):
#   kind    - incus | proxmox; required
#   out     - directory the build project and the image land in; required
#   dry_run - true prints the build commands without running them

_repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=scripts/meta/env/load.sh
. "${_repo_root}/scripts/meta/env/load.sh"

cd "${_repo_root}"

kind="${kind:-}"
out="${out:-}"
dry_run="${dry_run:-}"
if [ -z "${kind}" ] || [ -z "${out}" ]; then
	echo "agents-vm-template: pass kind=incus|proxmox and out=<dir>." >&2
	exit 2
fi

args=(--kind "${kind}" --out "${out}")
if [ "${dry_run}" = true ]; then
	args+=(--dry-run)
fi

exec "${PYTHON}" -m cli.agents.vm_template "${args[@]}"
