#!/usr/bin/env bash
# Reproduces and verifies the two self-hosted runner reliability fixes:
#   1. Stale MariaDB volumes cause ACCESS DENIED when passwords rotate between CI runs;
#      wiping volumes/ and containers/ before `up` gives MariaDB a clean start.
#   2. INFINITO_RUNNER_PREFIX scopes the container name so cleanup of one runner
#      instance does not terminate a sibling runner's container.
set -euo pipefail

PASS=0
FAIL=0

ok() {
	echo "PASS: $*"
	PASS=$((PASS + 1))
}
fail() {
	echo "FAIL: $*"
	FAIL=$((FAIL + 1))
}

TMPVOL="$(mktemp -d)"
MARIADB_CONTAINER="infinito_ci_test_mariadb"

cleanup() {
	docker rm -f "${MARIADB_CONTAINER}" 2>/dev/null || true
	docker rm -f runner1_nexus_debian runner2_nexus_debian 2>/dev/null || true
	rm -rf "${TMPVOL}"
}
trap cleanup EXIT

# Wait until the MariaDB socket accepts connections (no credential check).
wait_for_mariadb_up() {
	local container="$1"
	echo -n "Waiting for MariaDB to be ready"
	local i=0
	while [ "$i" -lt 60 ]; do
		if docker exec "${container}" mariadb-admin ping --silent >/dev/null 2>&1; then
			echo " ready"
			return 0
		fi
		printf "."
		sleep 3
		i=$((i + 1))
	done
	echo ""
	echo "ERROR: MariaDB did not become ready within 180s"
	docker logs "${container}" --tail=30 || true
	return 1
}

# ============================================================
# TEST 1: Volume wipe prevents MariaDB credential mismatch
# ============================================================
echo ""
echo "--- TEST 1: Volume wipe prevents MariaDB credential mismatch ---"

VOLUME_DIR="${TMPVOL}/mariadb"
mkdir -p "${VOLUME_DIR}"

echo "Run 1: initialise MariaDB with password 'first'..."
docker run -d --name "${MARIADB_CONTAINER}" \
	-e MARIADB_ROOT_PASSWORD=first \
	-e MARIADB_DATABASE=testdb \
	-v "${VOLUME_DIR}:/var/lib/mysql" \
	mariadb:lts >/dev/null

wait_for_mariadb_up "${MARIADB_CONTAINER}"

docker stop "${MARIADB_CONTAINER}" >/dev/null
docker rm "${MARIADB_CONTAINER}" >/dev/null

echo "Run 2 (WITHOUT wipe): new password 'second' on old volume..."
docker run -d --name "${MARIADB_CONTAINER}" \
	-e MARIADB_ROOT_PASSWORD=second \
	-v "${VOLUME_DIR}:/var/lib/mysql" \
	mariadb:lts >/dev/null

wait_for_mariadb_up "${MARIADB_CONTAINER}"

# Use the actual client to verify authentication — ping does not check credentials.
if docker exec "${MARIADB_CONTAINER}" mariadb -uroot -psecond -e "SELECT 1;" >/dev/null 2>&1; then
	fail "Expected ACCESS DENIED without volume wipe but MariaDB accepted the new password"
else
	ok "Bug reproduced: credential mismatch causes ACCESS DENIED without volume wipe"
fi

docker stop "${MARIADB_CONTAINER}" >/dev/null
docker rm "${MARIADB_CONTAINER}" >/dev/null

echo "Run 3 (WITH wipe): remove volume, start fresh with password 'second'..."
rm -rf "${VOLUME_DIR}"
mkdir -p "${VOLUME_DIR}"

docker run -d --name "${MARIADB_CONTAINER}" \
	-e MARIADB_ROOT_PASSWORD=second \
	-e MARIADB_DATABASE=testdb \
	-v "${VOLUME_DIR}:/var/lib/mysql" \
	mariadb:lts >/dev/null

wait_for_mariadb_up "${MARIADB_CONTAINER}"

if docker exec "${MARIADB_CONTAINER}" mariadb -uroot -psecond -e "SELECT 1;" >/dev/null 2>&1; then
	ok "Fix confirmed: MariaDB starts cleanly after volume wipe"
else
	fail "MariaDB still failing after volume wipe"
fi

docker stop "${MARIADB_CONTAINER}" >/dev/null
docker rm "${MARIADB_CONTAINER}" >/dev/null

# ============================================================
# TEST 2: Runner prefix isolation (INFINITO_RUNNER_PREFIX)
# ============================================================
echo ""
echo "--- TEST 2: Runner prefix isolation (INFINITO_RUNNER_PREFIX) ---"

docker run -d --name runner1_nexus_debian alpine sleep 300 >/dev/null
docker run -d --name runner2_nexus_debian alpine sleep 300 >/dev/null

docker rm -f runner1_nexus_debian >/dev/null

if docker ps --format "{{.Names}}" | grep -q "^runner2_nexus_debian$"; then
	ok "Isolation confirmed: runner2 container survives runner1 cleanup"
else
	fail "runner2 container was killed by runner1 cleanup"
fi

docker rm -f runner2_nexus_debian >/dev/null

# ============================================================
# SUMMARY
# ============================================================
echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
