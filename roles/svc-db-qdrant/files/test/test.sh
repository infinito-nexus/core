#!/usr/bin/env bash
# CLI test for svc-db-qdrant: the MCP endpoint honours its declared contract.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "${here}/shared/mcp/run.sh"
