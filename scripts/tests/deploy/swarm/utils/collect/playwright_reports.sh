#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/tests/deploy/swarm/utils/topology/base.sh
. "${SCRIPT_DIR}/../topology/base.sh"
# shellcheck source=/dev/null
source <(grep -E '^INFINITO_PLAYWRIGHT_REPORTS_BASE_DIR=' "${SCRIPT_DIR}/../../../../../../.env")

: "${APP_ID:?APP_ID required}"

dest="/tmp/playwright-artifacts/${APP_ID}"
mkdir -p "${dest}"

if ! timeout 10 docker exec "${MGR}" true 2>/dev/null; then
	echo "playwright_reports: manager ${MGR} unresponsive; reports skipped" >&2
	exit 124
fi

set +e
timeout --kill-after=30 120 docker exec "${MGR}" \
	tar -C "${INFINITO_PLAYWRIGHT_REPORTS_BASE_DIR}" -cf - . 2>/dev/null |
	tar -C "${dest}" -xf - 2>/dev/null
pipe_rc=("${PIPESTATUS[@]}")
set -e
producer_rc=${pipe_rc[0]}
consumer_rc=${pipe_rc[1]}

if [ "${producer_rc}" -eq 124 ] || [ "${producer_rc}" -eq 137 ]; then
	echo "playwright_reports: docker exec timed out (manager hung); reports skipped" >&2
	exit 124
fi

if [ "${producer_rc}" -ne 0 ] || [ "${consumer_rc}" -ne 0 ]; then
	echo "playwright_reports: collection failed (producer=${producer_rc} consumer=${consumer_rc}); reports may be partial" >&2
fi
