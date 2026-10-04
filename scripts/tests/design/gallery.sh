#!/usr/bin/env bash
# Rerun the design spec of one deployed app on the live stack and copy its
# before/after screenshots to /tmp/design-gallery/<app>/{before,after}/.
#
# Param app: deployed application id (required).
set -euo pipefail

: "${app:?app=<application_id> required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"
# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

reports="${INFINITO_PLAYWRIGHT_REPORTS_BASE_DIR}/${app}/design"
out="/tmp/design-gallery/${app}"

cmd="rm -rf '${reports}'" bash scripts/tests/deploy/local/exec/container.sh

spec_status=0
cmd="INFINITO_PLAYWRIGHT_KEEP=true bash scripts/tests/e2e/rerun-spec.sh '${app}' --grep 'design:'" \
	bash scripts/tests/deploy/local/exec/container.sh || spec_status=$?

rm -rf "${out}"
mkdir -p "${out}"
cmd="tar -C '${reports}' -cf - ." bash scripts/tests/deploy/local/exec/container.sh | tar -xf - -C "${out}"

echo "screenshots: ${out}"
exit "${spec_status}"
