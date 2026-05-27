#!/usr/bin/env bash
set -euo pipefail
echo "[docker-infinito] Starting infinito container"

if [[ "${1:-}" == "/sbin/init" ]]; then
	echo "[docker-infinito] Starting systemd as PID 1..."
	exec /sbin/init
fi

# Compute dynamically if not provided from outside
echo "[docker-infinito] before pkgmgr path"
INFINITO_PATH="$(pkgmgr path infinito)"
echo "[docker-infinito] after pkgmgr path: ${INFINITO_PATH}" # nocheck: container-bootstrap

# INFINITO_SRC_DIR is provided by compose / Dockerfile ENV. Assert strictly.
: "${INFINITO_SRC_DIR:?INFINITO_SRC_DIR must be set by the container environment}"
export INFINITO_PATH
export INFINITO_SRC_DIR

run_local_build() {
	echo "[docker-infinito] Build enabled (--compile)"
	echo "[docker-infinito] Using ${INFINITO_PATH} as working directory" # nocheck: container-bootstrap

	mkdir -p "${INFINITO_PATH}" # nocheck: container-bootstrap
	cd "${INFINITO_PATH}"       # nocheck: container-bootstrap

	echo "[docker-infinito] Copy ${INFINITO_SRC_DIR} to ${INFINITO_PATH}..."                        # nocheck: container-bootstrap
	rsync -a --delete --chown=root:root --exclude='.git' "${INFINITO_SRC_DIR}/" "${INFINITO_PATH}/" # nocheck: container-bootstrap

	echo "[docker-infinito] Reinstall via 'make install'..."
	make install

	echo "[docker-infinito] Installed:"
	pkgmgr version infinito
}

# Parse bootstrap flags. Each flag triggers its action directly; `--`
# terminates flag parsing so the rest of argv is the exec target.
while [[ $# -gt 0 ]]; do
	case "$1" in
	--compile)
		shift
		run_local_build
		;;
	--compile-silent)
		shift
		run_local_build >/dev/null 2>&1
		;;
	--)
		shift
		break
		;;
	*)
		break
		;;
	esac
done

# ---------------------------------------------------------------------------
# Hand off to infinito or arbitrary command
# ---------------------------------------------------------------------------
if [[ $# -eq 0 ]]; then
	echo "[docker-infinito] No arguments provided. Showing infinito help..."
	exec infinito --help
else
	cd "${INFINITO_PATH}" # nocheck: container-bootstrap
	exec "$@"
fi
