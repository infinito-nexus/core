#!/usr/bin/env bash
set -euo pipefail

# Mail-provider migration scenario (opt-in via INFINITO_TEST_MIGRATION):
#
#   Leg 1  Deploy web-app-mailu as the ACTIVE provider (the inventory pins
#          MAIL_PROVIDER=web-app-mailu) — simulates an existing
#          pre-Stalwart installation that owns mail.<domain> and the
#          public mail ports.
#   Leg 2  Regenerate the inventory with the default provider
#          (web-app-stalwart) and deploy BOTH roles over the KEPT docker
#          state — the exact upgrade path of a real Mailu installation:
#          Stalwart takes over mail.<domain> and the public mail ports,
#          Mailu parks on legacy-mail.<domain>.
#
# Both roles MUST be in leg 2's app list: without web-app-mailu in the
# group the legacy instance would keep its stale ACTIVE config (still
# binding the public mail ports) and collide with Stalwart.
#
# The per-deploy gates (hlth checks + the Playwright E2E stage) prove the
# post-migration mail stack; no separate assertion step is needed.
#
# Gating: INFINITO_TEST_MIGRATION (default.env: false). The manual CI
# workflow exposes a dispatch field for it, and a GitHub repository
# variable of the same name can enable it for scheduled runs.

: "${INFINITO_TEST_MIGRATION:?INFINITO_TEST_MIGRATION is not set — source scripts/meta/env/load.sh first}"

if [[ "${INFINITO_TEST_MIGRATION}" != "true" ]]; then
	echo ">>> Skipping mail-provider migration scenario (INFINITO_TEST_MIGRATION=${INFINITO_TEST_MIGRATION})."
	exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Pin one deterministic matrix round (all-on) — the migration scenario tests
# the provider switch, not the per-role variant matrix.
export variant="${variant:-0}"

echo "=== [migration 1/2] Deploy Mailu as the active mail provider ==="
INFINITO_INVENTORY_EXTRA_VARS='{"MAIL_PROVIDER": "web-app-mailu"}' \
	apps='web-app-mailu' \
	bash "${SCRIPT_DIR}/../initialize/selection.sh"

echo "=== [migration 2/2] Migrate: redeploy with the default provider over kept state ==="
apps='web-app-stalwart,web-app-mailu' \
	bash "${SCRIPT_DIR}/../initialize/selection.sh"

echo "=== Mail-provider migration scenario finished ==="
