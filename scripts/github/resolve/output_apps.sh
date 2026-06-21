#!/usr/bin/env bash
#
# Resolve the app list and write it to GITHUB_OUTPUT.
# Inputs via env (forwarded to scripts/meta/resolve/apps.sh):
#   INFINITO_DEPLOY_TYPE  — required (server|workstation|universal)
#   INFINITO_WHITELIST — optional space-separated allowlist
set -euo pipefail

apps="$(./scripts/meta/resolve/apps.sh)"
[[ -n "$apps" ]] || apps='[]'

# Expand the flat app-id list into deploy-matrix entries, splitting any role
# with more variants than INFINITO_VARIANT_BUNDLE_SIZE (default 3) into bundles
# of consecutive variant indices — one runner per bundle.
matrix="$(printf '%s' "$apps" | "${PYTHON:-python3}" -m utils.github.variant_bundles)"
[[ -n "$matrix" ]] || matrix='[]'

echo "apps=$matrix" >>"$GITHUB_OUTPUT"
echo "apps=$matrix"
