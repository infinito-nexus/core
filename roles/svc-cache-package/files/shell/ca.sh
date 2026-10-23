#!/usr/bin/env bash
# Install the frontend CA into the runner's trust store. Idempotent.
# See docs/contributing/environment/cache.md.
# Param: CA_ROOT  prefix for every absolute path below; empty in production.
set -eu

CA_ROOT="${CA_ROOT:-}"
CA_SRC="${CA_ROOT}/opt/package-frontend-ca.crt"
CA_NAME="infinito-package-frontend.crt"

if command -v update-ca-certificates >/dev/null 2>&1; then
	CA_DSTS=("${CA_ROOT}/usr/local/share/ca-certificates/${CA_NAME}")
	CA_REBUILD=(update-ca-certificates)
elif command -v update-ca-trust >/dev/null 2>&1; then
	CA_DSTS=(
		"${CA_ROOT}/etc/pki/ca-trust/source/anchors/${CA_NAME}"
		"${CA_ROOT}/etc/ca-certificates/trust-source/anchors/${CA_NAME}"
	)
	CA_REBUILD=(update-ca-trust extract)
else
	echo "[package-frontend-ca] no supported CA trust tool" >&2
	exit 1
fi

if [ ! -s "${CA_SRC}" ]; then
	echo "[package-frontend-ca] ${CA_SRC} empty/absent; cache profile inactive; skipping" >&2
	exit 0
fi

changed=0
for dst in "${CA_DSTS[@]}"; do
	if ! cmp -s "${CA_SRC}" "${dst}" 2>/dev/null; then
		install -d -m 0755 "$(dirname "${dst}")"
		install -m 0644 "${CA_SRC}" "${dst}"
		changed=1
	fi
done

if [ "${changed}" -eq 0 ]; then
	exit 0
fi

"${CA_REBUILD[@]}" >/dev/null 2>&1
echo "[package-frontend-ca] installed ${CA_DSTS[*]}" >&2
