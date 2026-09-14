#!/usr/bin/env bash
# CLI test for web-app-zammad: the MCP endpoint honours its declared contract,
# and the rails container can still reach the AI gateway when the tests run.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${here}/shared/mcp/run.sh"
bash "${here}/ai_gateway.sh"
