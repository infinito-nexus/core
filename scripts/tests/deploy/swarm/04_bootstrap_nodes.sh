#!/usr/bin/env bash
set -euo pipefail

HOST_SRC="$(pwd)"

HOST_SUDO=""
if [ "$(id -u)" -ne 0 ]; then
	HOST_SUDO="sudo -E"
fi

echo "==> Building .deb once on the act-runner"
DEB_PATH=$(PACKAGE_BUILD_ONLY=1 ${HOST_SUDO} bash "${HOST_SRC}/scripts/install/package.sh" |
	tee /dev/stderr | tail -n1)
[ -f "${DEB_PATH}" ] || {
	echo "FAILURE: builder did not produce a .deb (${DEB_PATH})"
	exit 1
}
echo "==> built ${DEB_PATH}"

DEB_BASENAME="$(basename "${DEB_PATH}")"

provision_node() {
	local node="$1"
	echo "==> [${node}] copying repo + .deb + installing"
	docker exec "${node}" mkdir -p /opt/infinito-nexus
	tar -C "${HOST_SRC}" -cf - . | docker exec -i "${node}" tar -C /opt/infinito-nexus -xpf -
	# docker cp to a tmpfs mount lands in the overlay shadow path (moby/22281).
	docker exec -i "${node}" sh -c "cat > /tmp/${DEB_BASENAME}" <"${DEB_PATH}"
	docker exec \
		-e LANG=C.UTF-8 -e LC_ALL=C.UTF-8 \
		-e PACKAGE_INSTALL_FROM="/tmp/${DEB_BASENAME}" \
		"${node}" bash -c \
		'cd /opt/infinito-nexus && bash scripts/install/package.sh'
}

declare -A PIDS
for node in "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}"; do
	provision_node "${node}" >"/tmp/bootstrap-${node}.log" 2>&1 &
	PIDS["${node}"]=$!
done

rc=0
for node in "${!PIDS[@]}"; do
	if ! wait "${PIDS[${node}]}"; then
		echo "FAILURE: provision_node ${node} exited non-zero"
		rc=1
	fi
done

for node in "${MGR}" "${WRK1}" "${WRK2}" "${NFS_SERVER}"; do
	echo "---- bootstrap log for ${node} ----"
	cat "/tmp/bootstrap-${node}.log"
done

exit "${rc}"
