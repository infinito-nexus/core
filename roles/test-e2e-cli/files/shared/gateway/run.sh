#!/usr/bin/env bash
# Env (rendered into test.env from the staging role's templates/test.env.j2):
#   GATEWAY_CONFIG_PATH   config file the role writes
#   GATEWAY_URL           OpenAI-compatible base URL the agent was pointed at
#   GATEWAY_KEY           key the agent presents
#   GATEWAY_MODEL         alias the agent asks for
set -euo pipefail

: "${GATEWAY_CONFIG_PATH?}"
: "${GATEWAY_URL?}"
: "${GATEWAY_KEY?}"
: "${GATEWAY_MODEL?}"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "${GATEWAY_URL}" ]; then
	echo "SKIP: this workstation was not pointed at a gateway by the deployment"
	exit 0
fi

python3 - <"${here}/probe.py"
