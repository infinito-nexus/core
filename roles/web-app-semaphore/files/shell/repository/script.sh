#!/usr/bin/env bash
# Args:
#   $1   the playbook of the template: the name of a script of this directory
#   $@   after $1, the arguments Semaphore hands that script
set -euo pipefail

SCRIPT="script.sh"
here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
# shellcheck source=lib.sh
source "${here}/lib.sh"

[ "$#" -gt 0 ] || refuse "the template names no script"
name="$1"
shift
[[ "${name}" =~ ^[a-z][a-z0-9-]*\.sh$ ]] || refuse "'${name}' is no script name"
[ -f "${here}/${name}" ] || refuse "${name} is no script of ${here}"
exec bash "${here}/${name}" "$@"
