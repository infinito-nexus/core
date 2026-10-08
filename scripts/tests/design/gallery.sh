#!/usr/bin/env bash
# Rerun the design spec of one deployed app on the live stack and copy its
# screenshots to /tmp/design-gallery/<app>/after/, with before=true also to before/.
#
# Param app: deployed application id (required).
# Param pw: Playwright arguments without quotes that replace the default `--grep design:` (optional). Such a run adds its screenshots to the existing ones instead of replacing them.
# Param views: comma-separated view names without spaces (optional). Only these views are captured, by the gallery test alone unless pw is set, and their screenshots are added to the existing ones.
# Param before: true also captures every view with the injected snippets stripped from the document (optional).
set -euo pipefail

: "${app:?app=<application_id> required}"

[[ "${before:-}" =~ ^(true)?$ ]] || {
	echo "before must be true or unset: ${before}" >&2
	exit 2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${REPO_ROOT}"
# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

reports="${INFINITO_PLAYWRIGHT_REPORTS_BASE_DIR}/${app}/design"
out="/tmp/design-gallery/${app}"

cmd="rm -rf '${reports}'" bash scripts/tests/deploy/local/exec/container.sh

selection="--grep design:"
if [[ -n "${views:-}" ]]; then
	[[ "${views}" =~ ^[A-Za-z0-9_,-]+$ ]] || {
		echo "views must be comma-separated view names without spaces: ${views}" >&2
		exit 2
	}
	selection="--grep gallery"
fi

spec_status=0
cmd="INFINITO_PLAYWRIGHT_KEEP=true PLAYWRIGHT_GALLERY_VIEWS='${views:-}' PLAYWRIGHT_GALLERY_BEFORE='${before:-}' bash scripts/tests/e2e/rerun-spec.sh '${app}' ${pw:-${selection}} --retries=0" \
	bash scripts/tests/deploy/local/exec/container.sh || spec_status=$?

[[ -n "${pw:-}${views:-}" ]] || rm -rf "${out}"
mkdir -p "${out}"
cmd="tar -C '${reports}' -cf - ." bash scripts/tests/deploy/local/exec/container.sh | tar -xf - -C "${out}"

echo "screenshots: ${out}"
exit "${spec_status}"
