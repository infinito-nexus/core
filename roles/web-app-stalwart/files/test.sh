#!/usr/bin/env bash
set -euo pipefail

# nocheck: raw-docker — standalone fixture harness for bare CI runners; the
# platform 'container' wrapper is deliberately NOT required here (the whole
# point is "no full infinito.nexus deploy needed").

# Standalone Mailu -> Stalwart migration test.
#
# "Mailu stump with some data, no full infinito.nexus deploy": Mailu keeps
# mail as standard Dovecot Maildir on its dovecot volume, so the migration
# source is that on-disk layout — this harness seeds exactly that tree and
# needs no running Mailu at all (which also proves the migration works
# against a stopped/legacy instance). The destination is one real Stalwart
# container, pinned to the role's SPOT (meta/services.yml).
#
# Procedure:
#   1. Start Stalwart (pinned image), wait for readiness.
#   2. Provision fixture domain + account via the management JMAP API
#      (same call shapes as tasks/03_provision_domain.yml / 04_manage_user.yml).
#   3. Seed the Mailu-layout maildir: INBOX (1 seen + 1 unseen), Archive (1).
#   4. Execute files/migrate_from_mailu.py.
#   5. Verify per IMAP: counts, subjects, preserved \Seen flag.
#   6. Re-run the migration and verify counts are unchanged (idempotency).
#
# Gated by INFINITO_TEST_MIGRATION (default.env: false); the CI workflow
# exposes a dispatch field and honors the INFINITO_TEST_MIGRATION GitHub
# repository variable.

if [[ "${INFINITO_TEST_MIGRATION:-}" != "true" ]]; then
	echo ">>> Skipping Mailu->Stalwart migration test (INFINITO_TEST_MIGRATION=${INFINITO_TEST_MIGRATION:-})."
	exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROLE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Image + version come from the role's SPOT so this test always exercises
# the exact pinned release the role deploys.
STALWART_IMAGE="$(sed -n 's/^  image: //p' "${ROLE_DIR}/meta/services.yml" | head -n1)"
STALWART_VERSION="$(sed -n 's/^  version: "\(v[^"]*\)"/\1/p' "${ROLE_DIR}/meta/services.yml" | head -n1)"
: "${STALWART_IMAGE:?could not read stalwart image from meta/services.yml}"
: "${STALWART_VERSION:?could not read stalwart version from meta/services.yml}"

CONTAINER="stalwart-migration-test"
JMAP_PORT=18080
IMAP_PORT=18993
ADMIN_USER="admin"
ADMIN_PASS="migration-test-secret"
DOMAIN="mailu-migration.test"
ACCOUNT_LOCAL="alice"
ACCOUNT="${ACCOUNT_LOCAL}@${DOMAIN}"
ACCOUNT_PASS="alice-fixture-secret"
JMAP_URL="http://127.0.0.1:${JMAP_PORT}/jmap/"

WORKDIR="$(mktemp -d)"
MAILDIR_ROOT="${WORKDIR}/mail"

cleanup() {
	docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
	rm -rf "${WORKDIR}"
}
trap cleanup EXIT

fail() {
	echo "FAIL: $*" >&2
	exit 1
}

jmap() {
	# nocheck: curl-timeout standalone bash harness — the Jinja curl filter is template-only
	curl -fsS --connect-timeout 5 --max-time 60 -u "${ADMIN_USER}:${ADMIN_PASS}" \
		-H "Content-Type: application/json" \
		--data-binary "$1" "${JMAP_URL}"
}

echo ">>> [1/6] Starting Stalwart ${STALWART_IMAGE}:${STALWART_VERSION}"
# Without a store config the image boots into bootstrap mode (setup port
# only, no IMAP) — mount the same one-object bootstrap the role uses, with
# an embedded RocksDB store instead of the platform PostgreSQL.
printf '{\n  "@type": "RocksDb",\n  "path": "/var/lib/stalwart/data"\n}\n' \
	>"${WORKDIR}/config.json"
docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
docker run -d --name "${CONTAINER}" \
	-p "127.0.0.1:${JMAP_PORT}:8080" \
	-p "127.0.0.1:${IMAP_PORT}:993" \
	-e STALWART_RECOVERY_ADMIN="${ADMIN_USER}:${ADMIN_PASS}" \
	-v "${WORKDIR}/config.json:/etc/stalwart/config.json:ro" \
	"${STALWART_IMAGE}:${STALWART_VERSION}" >/dev/null

echo ">>> Waiting for Stalwart readiness"
ready=0
for _ in $(seq 1 30); do
	# nocheck: curl-timeout standalone bash harness — the Jinja curl filter is template-only
	if curl -fsS --connect-timeout 5 --max-time 30 -o /dev/null "http://127.0.0.1:${JMAP_PORT}/healthz/ready" 2>/dev/null; then
		ready=1
		break
	fi
	sleep 2
done
[[ "${ready}" == "1" ]] || fail "Stalwart did not become ready"

echo ">>> [2/6] Provisioning fixture domain + account via JMAP"
jmap "{\"using\":[\"urn:ietf:params:jmap:core\",\"urn:stalwart:jmap\"],\"methodCalls\":[[\"x:Domain/set\",{\"create\":{\"d\":{\"name\":\"${DOMAIN}\"}}},\"c0\"]]}" >/dev/null
domain_id="$(jmap "{\"using\":[\"urn:ietf:params:jmap:core\",\"urn:stalwart:jmap\"],\"methodCalls\":[[\"x:Domain/get\",{\"ids\":null},\"c0\"]]}" |
	python3 -c "import json,sys; d=json.load(sys.stdin); print(next(x['id'] for x in d['methodResponses'][0][1]['list'] if x['name']=='${DOMAIN}'))")"
jmap "{\"using\":[\"urn:ietf:params:jmap:core\",\"urn:stalwart:jmap\"],\"methodCalls\":[[\"x:Account/set\",{\"create\":{\"a\":{\"@type\":\"User\",\"name\":\"${ACCOUNT_LOCAL}\",\"domainId\":\"${domain_id}\",\"description\":\"${ACCOUNT}\",\"credentials\":{\"0\":{\"@type\":\"Password\",\"secret\":\"${ACCOUNT_PASS}\"}}}}},\"c0\"]]}" >/dev/null

echo ">>> [3/6] Seeding the Mailu stump (Dovecot maildir layout)"
python3 "${SCRIPT_DIR}/tests/seed_mailu_maildir.py" "${MAILDIR_ROOT}" "${ACCOUNT}"

printf '{"%s": "%s"}\n' "${ACCOUNT}" "${ACCOUNT_PASS}" >"${WORKDIR}/accounts.json"

echo ">>> [4/6] Executing the migration script"
python3 "${SCRIPT_DIR}/migrate_from_mailu.py" \
	--maildir-root "${MAILDIR_ROOT}" \
	--imap-host 127.0.0.1 \
	--imap-port "${IMAP_PORT}" \
	--imap-insecure \
	--accounts-file "${WORKDIR}/accounts.json"

echo ">>> [5/6] Verifying migrated data over IMAP"
python3 "${SCRIPT_DIR}/tests/verify_migration.py" \
	127.0.0.1 "${IMAP_PORT}" "${ACCOUNT}" "${ACCOUNT_PASS}"

echo ">>> [6/6] Idempotency: second run must not duplicate"
python3 "${SCRIPT_DIR}/migrate_from_mailu.py" \
	--maildir-root "${MAILDIR_ROOT}" \
	--imap-host 127.0.0.1 \
	--imap-port "${IMAP_PORT}" \
	--imap-insecure \
	--accounts-file "${WORKDIR}/accounts.json"
python3 "${SCRIPT_DIR}/tests/verify_migration.py" \
	127.0.0.1 "${IMAP_PORT}" "${ACCOUNT}" "${ACCOUNT_PASS}"

echo "Migration test passed."
