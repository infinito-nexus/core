#!/usr/bin/env bash
# Mailu → Stalwart migration, end to end against the deployed stack:
#   mail is delivered into the legacy Mailu, the role's import switch is turned on and
#   applied, and the same messages are then read back out of Stalwart over IMAP.
# nocheck: raw-docker — storage assertions read the maildir volume via the container wrapper
set -euo pipefail

: "${STALWART_MIGRATION_E2E:?missing STALWART_MIGRATION_E2E}"
if [[ "${STALWART_MIGRATION_E2E}" != "true" ]]; then
	echo "SKIP: web-app-mailu is not co-deployed; nothing to migrate."
	exit 0
fi

: "${TEST_INVENTORY_DIR:?missing TEST_INVENTORY_DIR}"
: "${PYTHON_BIN:?missing PYTHON_BIN}"
: "${REPO_SRC_DIR:?missing REPO_SRC_DIR}"
: "${ADMIN_EMAIL:?missing ADMIN_EMAIL}"
: "${ADMIN_IMAP_PASSWORD:?missing ADMIN_IMAP_PASSWORD}"
: "${BIBER_EMAIL:?missing BIBER_EMAIL}"
: "${BIBER_IMAP_PASSWORD:?missing BIBER_IMAP_PASSWORD}"
: "${MAILU_MAILDIR_VOLUME:?missing MAILU_MAILDIR_VOLUME}"
: "${MAILU_SMTP_CONTAINER:?missing MAILU_SMTP_CONTAINER}"
: "${MAIL_DOMAIN:?missing MAIL_DOMAIN}"

RUN_ID="$(date +%s)"
SUBJ_A="infinito-mig-A-${RUN_ID}"
SUBJ_B="infinito-mig-B-${RUN_ID}"
SUBJ_C="infinito-mig-C-${RUN_ID}"
SUBJ_D="infinito-mig-D-${RUN_ID}"

WORKDIR="$(mktemp -d)"
cleanup() { rm -rf "${WORKDIR}"; }
trap cleanup EXIT

compose_mail() {
	local from="$1" rcpt="$2" subject="$3" in_reply_to="${4:-}"
	{
		printf 'From: %s\r\nTo: %s\r\nSubject: %s\r\n' "${from}" "${rcpt}" "${subject}"
		printf 'Message-ID: <%s@%s>\r\nDate: %s\r\n' "${subject}" "${MAIL_DOMAIN}" "$(date -R)"
		if [[ -n "${in_reply_to}" ]]; then
			printf 'In-Reply-To: <%s@%s>\r\n' "${in_reply_to}" "${MAIL_DOMAIN}"
		fi
		printf '\r\n%s\r\n' "migration e2e body ${subject}"
	} >"${WORKDIR}/mail.eml"
}

send_smtp() {
	local host="$1" from="$2" rcpt="$3" subject="$4" attempt
	for attempt in 1 2 3 4 5 6; do
		if curl -sS --connect-timeout 10 --max-time 60 --url "smtp://${host}:25" \
			--mail-from "${from}" --mail-rcpt "${rcpt}" \
			--upload-file "${WORKDIR}/mail.eml"; then
			echo "sent: ${subject} (${from} -> ${rcpt} via ${host})"
			return 0
		fi
		echo "retry ${attempt}: submission of ${subject} to ${host} failed; waiting 10s"
		sleep 10
	done
	echo "FAIL: could not submit ${subject} to ${host}" >&2
	return 1
}

wait_stored_in_maildir() {
	local subject="$1" mountpoint="$2" attempt
	for attempt in $(seq 1 30); do
		if grep -rqF "Subject: ${subject}" "${mountpoint}" 2>/dev/null; then
			echo "stored: ${subject} under ${mountpoint}"
			return 0
		fi
		sleep 5
	done
	echo "FAIL: ${subject} never appeared under ${mountpoint}" >&2
	return 1
}

wait_in_imap() {
	local user="$1" password="$2" subject="$3" attempt mailbox
	# Exception: the .test domain publishes no mail-auth DNS, so Stalwart files authenticated
	# mail into "Junk Mail" (its \Junk folder) rather than INBOX — both must be searched.
	for attempt in $(seq 1 30); do
		for mailbox in INBOX Junk%20Mail; do
			if curl -sS --connect-timeout 10 --max-time 60 --insecure \
				--url "imaps://127.0.0.1:993/${mailbox}" \
				--user "${user}:${password}" \
				--request "SEARCH SUBJECT \"${subject}\"" 2>/dev/null |
				grep -qE 'SEARCH [0-9]'; then
				echo "found: ${subject} in ${user}'s ${mailbox}"
				return 0
			fi
		done
		sleep 5
	done
	echo "FAIL: ${subject} not found over IMAP for ${user}" >&2
	return 1
}

# Exception: ansible's plugin loader imports the repo's `plugins` package by name, so the
# nested playbook needs the repo root on PYTHONPATH.
run_import() {
	(
		cd "${REPO_SRC_DIR}"
		PYTHONPATH="${REPO_SRC_DIR}" "${PYTHON_BIN}" -m cli.administration.deploy.dedicated \
			"${TEST_INVENTORY_DIR}/devices.yml" -p "${TEST_INVENTORY_DIR}/.password" \
			-vv --diff --skip-backup --skip-cleanup \
			--id web-app-stalwart \
			-e 'TEST_E2E_ENABLED=false' \
			-e 'STALWART_MIGRATION_NESTED=true' \
			-e 'STALWART_IMPORT_MAILU=true'
	)
}

echo "=== [1/4] Deliver mail into the legacy Mailu (A: biber->admin, B: admin's reply) ==="
MAILU_SMTP_IP="$(container inspect --type container -f '{{ range .NetworkSettings.Networks }}{{ .IPAddress }} {{ end }}' "${MAILU_SMTP_CONTAINER}" | awk '{print $1}')"
echo "mailu smtp at ${MAILU_SMTP_IP}"
compose_mail "${BIBER_EMAIL}" "${ADMIN_EMAIL}" "${SUBJ_A}"
send_smtp "${MAILU_SMTP_IP}" "${BIBER_EMAIL}" "${ADMIN_EMAIL}" "${SUBJ_A}"
compose_mail "${ADMIN_EMAIL}" "${BIBER_EMAIL}" "${SUBJ_B}" "${SUBJ_A}"
send_smtp "${MAILU_SMTP_IP}" "${ADMIN_EMAIL}" "${BIBER_EMAIL}" "${SUBJ_B}"

echo "=== [2/4] Confirm the messages are stored in Mailu's maildir ==="
MAILDIR_MOUNT="$(container volume inspect --format '{{ .Mountpoint }}' "${MAILU_MAILDIR_VOLUME}")"
wait_stored_in_maildir "${SUBJ_A}" "${MAILDIR_MOUNT}/${ADMIN_EMAIL}"
wait_stored_in_maildir "${SUBJ_B}" "${MAILDIR_MOUNT}/${BIBER_EMAIL}"

echo "=== [3/4] Migrate: run the role with the import switch on ==="
run_import

echo "=== [4/4] Continuity in Stalwart, then live flow (C: biber->admin, D: admin's reply) ==="
wait_in_imap "${ADMIN_EMAIL}" "${ADMIN_IMAP_PASSWORD}" "${SUBJ_A}"
wait_in_imap "${BIBER_EMAIL}" "${BIBER_IMAP_PASSWORD}" "${SUBJ_B}"
compose_mail "${BIBER_EMAIL}" "${ADMIN_EMAIL}" "${SUBJ_C}"
send_smtp "127.0.0.1" "${BIBER_EMAIL}" "${ADMIN_EMAIL}" "${SUBJ_C}"
compose_mail "${ADMIN_EMAIL}" "${BIBER_EMAIL}" "${SUBJ_D}" "${SUBJ_C}"
send_smtp "127.0.0.1" "${ADMIN_EMAIL}" "${BIBER_EMAIL}" "${SUBJ_D}"
wait_in_imap "${ADMIN_EMAIL}" "${ADMIN_IMAP_PASSWORD}" "${SUBJ_C}"
wait_in_imap "${BIBER_EMAIL}" "${BIBER_IMAP_PASSWORD}" "${SUBJ_D}"

echo "MIGRATION STATE MACHINE COMPLETE"
