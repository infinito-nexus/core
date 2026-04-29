#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Trust Infinito Root CA from running container on the host system
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source project defaults so INFINITO_CONTAINER auto-derives from
# INFINITO_DISTRO (single SPOT in scripts/meta/env/defaults.sh) — callers
# only need to set INFINITO_DISTRO.
# shellcheck source=scripts/meta/env/defaults.sh
source "${SCRIPT_DIR}/../../../meta/env/defaults.sh"

CONTAINER_NAME="${INFINITO_CONTAINER}"
CA_SRC_PATH="/etc/infinito.nexus/ca/root-ca.crt"
CA_DST_DIR="/etc/infinito.nexus/ca"
CA_DST_PATH="${CA_DST_DIR}/root-ca.crt"
CA_TRUST_NAME="infinito-root-ca"

WITH_CA_TRUST_SCRIPT="${SCRIPT_DIR}/../../../../roles/sys-ca-selfsigned/files/with-ca-trust.sh"

log() {
	echo "[trust-ca] $*" >&2
}

require() {
	if ! command -v "$1" >/dev/null 2>&1; then
		echo "[trust-ca] ERROR: required command not found: $1" >&2
		exit 1
	fi
}

# --- checks ------------------------------------------------------------------

require docker
require sudo

if [ -z "$CONTAINER_NAME" ]; then
	echo "[trust-ca] ERROR: INFINITO_CONTAINER is not set" >&2
	exit 2
fi

if [ ! -f "$WITH_CA_TRUST_SCRIPT" ]; then
	echo "[trust-ca] ERROR: with-ca-trust.sh not found at $WITH_CA_TRUST_SCRIPT" >&2
	exit 3
fi

log "Using container: $CONTAINER_NAME"
log "CA source path (container): $CA_SRC_PATH"
log "CA destination path (host): $CA_DST_PATH"

# --- extract CA ---------------------------------------------------------------

log "Extracting Root CA from container"
sudo mkdir -p "$CA_DST_DIR"

sudo docker cp \
	"${CONTAINER_NAME}:${CA_SRC_PATH}" \
	"$CA_DST_PATH"

sudo chmod 0644 "$CA_DST_PATH"

# --- trust CA -----------------------------------------------------------------

log "Installing CA into host trust store"

sudo \
	CA_TRUST_CERT="$CA_DST_PATH" \
	CA_TRUST_NAME="$CA_TRUST_NAME" \
	VERBOSE=1 \
	bash "$WITH_CA_TRUST_SCRIPT"

log "CA trust installation completed successfully"

echo
echo "✅ Root CA trusted on host system"
echo "ℹ️  Restart browsers (Chrome / Firefox) if already running"
