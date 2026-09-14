#!/usr/bin/env bash
# Param: MATRIX_MDAD_VOLUME     - docker volume holding the bootstrap marker
# Param: MATRIX_MDAD_CONTAINER  - the DiD runner container
set -euo pipefail

: "${MATRIX_MDAD_VOLUME:?}"
: "${MATRIX_MDAD_CONTAINER:?}"

if _mp="$(container volume inspect -f '{{ .Mountpoint }}' "$MATRIX_MDAD_VOLUME" 2>/dev/null)"; then
	rm -f "${_mp}/bootstrap.done"
fi

if container ps -q -f "name=^${MATRIX_MDAD_CONTAINER}$" | grep -q .; then
	container restart "$MATRIX_MDAD_CONTAINER"
fi
