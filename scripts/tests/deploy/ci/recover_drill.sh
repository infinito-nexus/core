#!/usr/bin/env bash
# Compose-side full-recovery verification. Runs inside the single-host compose
# deploy container, where every recovery target is local -> `recover full`
# fits. Seeds a backup root (nfs + volume + secrets, each with a marker) plus a
# docker volume, then `recover full <root> localhost` restores every
# backup-stored type into its live target and the markers are verified.
#
# Verifies the `full` orchestrator + discovery + the per-type recover.py end to
# end. The backup tree is seeded (not produced by a real backup run -- the
# multi-node swarm DR drill covers the real backup->recover chain).
#
# Destructive: nfs/secrets recover with `rsync --delete` into the live system
# paths (/srv/nfs/infinito-state, /var/lib/infinito/secrets), so this must be
# the last step before teardown and only ever inside the disposable CI
# container -- never on a host whose state matters.
set -euo pipefail

REPO="${INFINITO_REPO_ROOT:-/opt/src/infinito}"
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

echo "==> [1/3] seed backup root + docker volume"
rm -rf "${ROOT}"
mkdir -p "${NFS_FILES}" "${SEC_FILES}" "${VOL_FILES}" \
	/srv/nfs/infinito-state /var/lib/infinito/secrets
printf '%s' "${TOKEN}" >"${NFS_FILES}/${MARKER}"
printf '%s' "${TOKEN}" >"${SEC_FILES}/${MARKER}"
printf '%s' "${TOKEN}" >"${VOL_FILES}/${MARKER}"
docker volume rm -f "${VOL}" >/dev/null 2>&1 || true
docker volume create "${VOL}" >/dev/null

echo "==> [2/3] recover full ${ROOT} localhost (nfs -> volume -> secrets)"
PYTHONPATH="${REPO}" python3 -m cli.administration.recover \
	full "${ROOT}" localhost --no-safety-backup

echo "==> [3/3] verify restored markers"
grep -qF "${TOKEN}" "/srv/nfs/infinito-state/${MARKER}"
echo "    OK nfs marker restored to /srv/nfs/infinito-state"
grep -qF "${TOKEN}" "/var/lib/docker/volumes/${VOL}/_data/${MARKER}"
echo "    OK volume marker restored to docker volume ${VOL}"
grep -qF "${TOKEN}" "/var/lib/infinito/secrets/${MARKER}"
echo "    OK secrets marker restored to /var/lib/infinito/secrets"

docker volume rm -f "${VOL}" >/dev/null 2>&1 || true
echo "==> compose recover drill PASSED (full: nfs -> volume -> secrets)"
