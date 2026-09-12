#!/usr/bin/env bash
# CLI test for web-app-n8n: the MCP endpoint honours its declared contract.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${here}/shared/mcp/run.sh"
