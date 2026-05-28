#!/usr/bin/env bash
set -euo pipefail
echo "[docker-infinito] Starting infinito container"

if [[ "${1:-}" == "/sbin/init" ]]; then
	echo "[docker-infinito] Starting systemd as PID 1..."
	exec /sbin/init
fi

: "${INFINITO_SRC_DIR:?INFINITO_SRC_DIR must be set by the container environment}"
export INFINITO_SRC_DIR

run_local_build() {
	echo "[docker-infinito] Build enabled (--compile)"
	cd "${INFINITO_SRC_DIR}"
	echo "[docker-infinito] Reinstall via 'make install' in ${INFINITO_SRC_DIR}..."
	make install
	echo "[docker-infinito] Installed:"
	infinito --version || true
}

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

if [[ $# -eq 0 ]]; then
	echo "[docker-infinito] No arguments provided. Showing infinito help..."
	exec infinito --help
else
	cd "${INFINITO_SRC_DIR}"
	exec "$@"
fi
