#!/usr/bin/env bash
set -euo pipefail

# Build the licence inventory of the tree so the counsel's checks start from
# deterministic data: the project licence and every role's
# declared licence under roles/*/meta/license.yml. Image licences come from a
# running instance and are probed separately (make legal-probe).

_repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "${_repo_root}"

echo "# Project licence"
if [ -f LICENSE ]; then
	echo "LICENSE"
else
	echo "(no LICENSE file at the repo root)"
fi

echo "# Declared role licences (roles/*/meta/license.yml)"
find roles -type f -path '*/meta/license.yml' | sort
