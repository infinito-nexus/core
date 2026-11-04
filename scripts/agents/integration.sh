#!/usr/bin/env bash
set -euo pipefail

# Run the SaaS integration workflow locally through act: the app matrix of
# call-test-deploy.yml, each app deployed together with the agents bundle, with
# local models only, one app after the other. CI runs the
# same file in parallel.
# Inputs (env):
#   whitelist - space-separated app ids to integrate (empty: diff vs main)
#   priority  - space-separated app ids to integrate first

_repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=scripts/meta/env/load.sh
. "${_repo_root}/scripts/meta/env/load.sh"

cd "${_repo_root}"

ACT_WORKFLOW=".github/workflows/call-test-agents-saas.yml" \
	ACT_INPUTS="whitelist=${whitelist:-} priority=${priority:-} modes=compose" \
	bash scripts/tests/deploy/act/workflow.sh
