#!/usr/bin/env bash
# Compose-side full-recovery verification. Runs inside the single-host compose
# deploy container, where every recovery target is local -> `recover full`
# fits. Seeds a backup root (nfs + secrets, plus a docker volume when the
# container has an inner docker daemon), then `recover full <root> localhost`
# restores every seeded type into its live target and the markers are
# verified. Non-stack role deploys carry no inner dockerd; they still drill
# the nfs + secrets legs because the full planner only recovers repos that
# exist under the backup root.
#
# Verifies the `full` orchestrator + discovery + the per-type recover.py end to
# end. The backup tree is seeded (not produced by a real backup run -- the
# multi-node swarm DR drill covers the real backup->recover chain).
#
# Destructive: nfs/secrets recover with `rsync --delete` into the live system
# paths, so this must be the last step before teardown and only ever inside
# the disposable CI container -- never on a host whose state matters.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
DIR_SECRETS="$(PYTHONPATH="${REPO}" python3 -c 'from utils.paths import DIR_SECRETS; print(DIR_SECRETS)')"
NFS_STATE="$(PYTHONPATH="${REPO}" python3 -c 'from cli.administration.recover.paths import NFS_EXPORT_STATE; print(NFS_EXPORT_STATE)')"
VOL="recoverdrill_data"
TOKEN="compose-recover-drill"
MARKER=".recoverdrill-marker"
ROOT="/tmp/recoverdrill-backup"
GEN="20260101000000"
NFS_FILES="${ROOT}/HASH/backup-nfs-to-local/${GEN}/files"
SEC_FILES="${ROOT}/HASH/backup-secrets-to-local/${GEN}/files/secrets"
VOL_FILES="${ROOT}/HASH/backup-docker-to-local/${GEN}/${VOL}/files"

if ! command -v rsync >/dev/null; then
	echo "SKIP recover drill: rsync not available in this image"
	exit 0
fi

HAVE_DOCKER=1
if ! docker info >/dev/null 2>&1; then
	HAVE_DOCKER=0
	echo "NOTE recover drill: no docker daemon (non-stack role deploy) -> volume leg skipped, nfs+secrets still drilled"
fi

echo "==> [1/3] seed backup root"
rm -rf "${ROOT}"
mkdir -p "${NFS_FILES}" "${SEC_FILES}" "${NFS_STATE}" "${DIR_SECRETS}"
printf '%s' "${TOKEN}" >"${NFS_FILES}/${MARKER}"
printf '%s' "${TOKEN}" >"${SEC_FILES}/${MARKER}"
if [ "${HAVE_DOCKER}" = "1" ]; then
	mkdir -p "${VOL_FILES}"
	printf '%s' "${TOKEN}" >"${VOL_FILES}/${MARKER}"
	docker volume rm -f "${VOL}" >/dev/null 2>&1 || true
	docker volume create "${VOL}" >/dev/null
fi

echo "==> [2/3] recover full ${ROOT} localhost (the full planner recovers every seeded repo)"
PYTHONPATH="${REPO}" python3 -m cli.administration.recover \
	full "${ROOT}" localhost --no-safety-backup

echo "==> [3/3] verify restored markers"
grep -qF "${TOKEN}" "${NFS_STATE}/${MARKER}"
echo "    OK nfs marker restored to ${NFS_STATE}"
grep -qF "${TOKEN}" "${DIR_SECRETS}/${MARKER}"
echo "    OK secrets marker restored to ${DIR_SECRETS}"
if [ "${HAVE_DOCKER}" = "1" ]; then
	grep -qF "${TOKEN}" "/var/lib/docker/volumes/${VOL}/_data/${MARKER}"
	echo "    OK volume marker restored to docker volume ${VOL}"
	docker volume rm -f "${VOL}" >/dev/null 2>&1 || true
	echo "==> compose recover drill PASSED (full: nfs -> volume -> secrets)"
else
	echo "==> compose recover drill PASSED (nfs -> secrets; volume leg skipped without docker)"
fi
