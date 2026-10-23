#!/usr/bin/env bash
# nocheck: raw-docker — storage assertions read the maildir volume via the container wrapper
set -euo pipefail

: "${STALWART_MIGRATION_E2E:?missing STALWART_MIGRATION_E2E}"
if [[ "${STALWART_MIGRATION_E2E}" != "true" ]]; then
	echo "SKIP: web-app-mailu is not co-deployed; nothing to migrate."
	exit 0
fi

: "${PYTHON_BIN:?missing PYTHON_BIN}"
: "${MIGRATION_SCRIPT:?missing MIGRATION_SCRIPT}"
: "${ADMIN_EMAIL:?missing ADMIN_EMAIL}"
: "${BIBER_EMAIL:?missing BIBER_EMAIL}"
: "${MAILU_MAILDIR_VOLUME:?missing MAILU_MAILDIR_VOLUME}"
: "${MAILU_SMTP_CONTAINER:?missing MAILU_SMTP_CONTAINER}"
: "${MAIL_DOMAIN:?missing MAIL_DOMAIN}"
: "${STALWART_ADMIN_USER:?missing STALWART_ADMIN_USER}"
: "${STALWART_ADMIN_PASSWORD:?missing STALWART_ADMIN_PASSWORD}"
: "${STALWART_JMAP_URL:?missing STALWART_JMAP_URL}"
: "${STALWART_MAILBOX_MAP:?missing STALWART_MAILBOX_MAP}"

RUN_ID="$(date +%s)"
SUBJ_A="infinito-mig-A-${RUN_ID}"
SUBJ_B="infinito-mig-B-${RUN_ID}"
SUBJ_C="infinito-mig-C-${RUN_ID}"
SUBJ_D="infinito-mig-D-${RUN_ID}"
SUBJ_E="infinito-mig-E-${RUN_ID}"
SUBJ_F="infinito-mig-F-${RUN_ID}"
SUBJ_G="infinito-mig-G-${RUN_ID}"
SUBJ_H="infinito-mig-H-${RUN_ID}"
SUBJ_S="infinito-mig-S-${RUN_ID}"
STRAY="mig-${RUN_ID}@${MAIL_DOMAIN}"
FOREIGN_DOMAIN="foreign-${RUN_ID}.invalid"
FOREIGN="mig-${RUN_ID}@${FOREIGN_DOMAIN}"
SEEDED_EPOCH=1700000000

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

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
		if "${PYTHON_BIN}" "${SCRIPT_DIR}/../probe/mail.py" send \
			"${host}" "${from}" "${rcpt}" "${WORKDIR}/mail.eml"; then
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

wait_delivered() {
	local address="$1" subject="$2" attempt mailbox
	for attempt in $(seq 1 30); do
		for mailbox in "INBOX" "Junk Mail"; do
			if "${PYTHON_BIN}" "${SCRIPT_DIR}/../probe/stalwart.py" message \
				"${address}" "${mailbox}" "${subject}" "-" "-" 2>/dev/null; then
				echo "found: ${subject} in ${address}/${mailbox}"
				return 0
			fi
		done
		sleep 5
	done
	echo "FAIL: ${subject} not delivered to ${address}" >&2
	return 1
}

wait_message() {
	local address="$1" mailbox="$2" subject="$3" flags="$4" epoch="$5" attempt
	for attempt in $(seq 1 30); do
		if "${PYTHON_BIN}" "${SCRIPT_DIR}/../probe/stalwart.py" message \
			"${address}" "${mailbox}" "${subject}" "${flags}" "${epoch}"; then
			echo "found: ${subject} in ${address}/${mailbox} (flags ${flags}, date ${epoch})"
			return 0
		fi
		sleep 5
	done
	echo "FAIL: ${subject} not in ${address}/${mailbox} with flags ${flags} and date ${epoch}" >&2
	return 1
}

seed_message() {
	local folder="$1" file="$2" from="$3" rcpt="$4" subject="$5"
	mkdir -p "${folder}/cur" "${folder}/new" "${folder}/tmp"
	printf 'From: %s\r\nTo: %s\r\nSubject: %s\r\nMessage-ID: <%s@%s>\r\nDate: %s\r\n\r\nseeded %s\r\n' \
		"${from}" "${rcpt}" "${subject}" "${subject}" "${MAIL_DOMAIN}" "$(date -R -d "@${SEEDED_EPOCH}")" "${subject}" \
		>"${folder}/cur/${file}"
	touch -d "@${SEEDED_EPOCH}" "${folder}/cur/${file}"
	echo "seeded: ${subject} into ${folder}"
}

expect_line() {
	local log="$1" needle="$2"
	if ! grep -qF -- "${needle}" "${log}"; then
		echo "FAIL: the import output lacks '${needle}'" >&2
		cat "${log}" >&2
		return 1
	fi
	echo "import reported: ${needle}"
}

run_migration() {
	local maildir="$1" log="$2"
	"${PYTHON_BIN}" -c \
		'import json, os, sys; json.dump({"user": os.environ["STALWART_ADMIN_USER"], "password": os.environ["STALWART_ADMIN_PASSWORD"]}, open(sys.argv[1], "w"))' \
		"${WORKDIR}/admin.json"
	chmod 600 "${WORKDIR}/admin.json"

	"${PYTHON_BIN}" "${MIGRATION_SCRIPT}" \
		--maildir-root "${maildir}" \
		--imap-host 127.0.0.1 --imap-port 993 --imap-insecure \
		--jmap-url "${STALWART_JMAP_URL}" \
		--admin-file "${WORKDIR}/admin.json" \
		--mailbox-map "${STALWART_MAILBOX_MAP}" \
		--workers "${STALWART_IMPORT_WORKERS}" \
		--done-file "${WORKDIR}/import.done" | tee "${log}"

	rm -f "${WORKDIR}/admin.json"
}

MAPPED_SOURCE="$("${PYTHON_BIN}" -c 'import json, sys; m = json.loads(sys.argv[1]); print(m[0]["source"].lower() if m else "")' "${STALWART_MAILBOX_MAP}")"
MAPPED_TARGET="$("${PYTHON_BIN}" -c 'import json, sys; m = json.loads(sys.argv[1]); print(m[0]["target"].lower() if m else "")' "${STALWART_MAILBOX_MAP}")"

echo "=== [1/7] Deliver mail into the legacy Mailu (A: biber->admin, B: admin's reply) ==="
MAILU_SMTP_IP="$(container inspect --type container -f '{{ range .NetworkSettings.Networks }}{{ .IPAddress }} {{ end }}' "${MAILU_SMTP_CONTAINER}" | awk '{print $1}')"
case "${MAILU_SMTP_IP}" in
[0-9]*.[0-9]*.[0-9]*.[0-9]*) ;;
*)
	echo "FAIL: ${MAILU_SMTP_CONTAINER} has no IPv4 address (got '${MAILU_SMTP_IP}'); the legacy Mailu stack is not running" >&2
	exit 1
	;;
esac
echo "mailu smtp at ${MAILU_SMTP_IP}"
compose_mail "${BIBER_EMAIL}" "${ADMIN_EMAIL}" "${SUBJ_A}"
send_smtp "${MAILU_SMTP_IP}" "${BIBER_EMAIL}" "${ADMIN_EMAIL}" "${SUBJ_A}"
compose_mail "${ADMIN_EMAIL}" "${BIBER_EMAIL}" "${SUBJ_B}" "${SUBJ_A}"
send_smtp "${MAILU_SMTP_IP}" "${ADMIN_EMAIL}" "${BIBER_EMAIL}" "${SUBJ_B}"

echo "=== [2/7] Confirm the messages are stored in Mailu's maildir ==="
MAILDIR_MOUNT="$(container volume inspect --format '{{ .Mountpoint }}' "${MAILU_MAILDIR_VOLUME}")"
wait_stored_in_maildir "${SUBJ_A}" "${MAILDIR_MOUNT}/${ADMIN_EMAIL}"
wait_stored_in_maildir "${SUBJ_B}" "${MAILDIR_MOUNT}/${BIBER_EMAIL}"

echo "=== [3/7] Seed mailboxes Mailu created outside the inventory (SSO, admin UI, foreign domain) ==="
seed_message "${MAILDIR_MOUNT}/${STRAY}" "e.seed:2,S" "${BIBER_EMAIL}" "${STRAY}" "${SUBJ_E}"
seed_message "${MAILDIR_MOUNT}/${STRAY}/.Projects" "f.seed:2,F" "${BIBER_EMAIL}" "${STRAY}" "${SUBJ_F}"
mkdir -p "${MAILDIR_MOUNT}/${STRAY}/sieve"
printf 'require ["fileinto"];\nif header :contains "subject" "%s" {\n  fileinto "Projects";\n}\n' "${SUBJ_S}" \
	>"${MAILDIR_MOUNT}/${STRAY}/sieve/projects.sieve"
ln -sfn sieve/projects.sieve "${MAILDIR_MOUNT}/${STRAY}/.dovecot.sieve"
seed_message "${MAILDIR_MOUNT}/${FOREIGN}" "h.seed:2,S" "${BIBER_EMAIL}" "${FOREIGN}" "${SUBJ_H}"
if [[ -n "${MAPPED_SOURCE}" ]]; then
	seed_message "${MAILDIR_MOUNT}/${MAPPED_SOURCE}/.Projects" "g.seed:2,S" "${ADMIN_EMAIL}" "${MAPPED_SOURCE}" "${SUBJ_G}"
fi

echo "=== [4/7] Migrate: run the import script against the deployed stack ==="
run_migration "${MAILDIR_MOUNT}" "${WORKDIR}/import-1.log"
expect_line "${WORKDIR}/import-1.log" "[ACCOUNT] created ${STRAY}"
expect_line "${WORKDIR}/import-1.log" "[MAILBOX] ${STRAY} -> ${STRAY}: found=2 imported=2 skipped=0 failed=0 sieve=imported:projects (active)"
expect_line "${WORKDIR}/import-1.log" "[SKIP] ${FOREIGN}: domain ${FOREIGN_DOMAIN} is not served by Stalwart"
if [[ -n "${MAPPED_SOURCE}" ]]; then
	expect_line "${WORKDIR}/import-1.log" "[MAILBOX] ${MAPPED_SOURCE} -> ${MAPPED_TARGET}:"
fi

echo "=== [5/7] Folders, flags, dates, Sieve, mapping and skipped domains in Stalwart ==="
wait_delivered "${ADMIN_EMAIL}" "${SUBJ_A}"
wait_delivered "${BIBER_EMAIL}" "${SUBJ_B}"
wait_message "${STRAY}" "INBOX" "${SUBJ_E}" '\Seen' "${SEEDED_EPOCH}"
wait_message "${STRAY}" "Projects" "${SUBJ_F}" '\Flagged' "${SEEDED_EPOCH}"
"${PYTHON_BIN}" "${SCRIPT_DIR}/../probe/stalwart.py" absent domain "${FOREIGN_DOMAIN}"
echo "absent: domain ${FOREIGN_DOMAIN} was not created"
if [[ -n "${MAPPED_SOURCE}" ]]; then
	wait_message "${MAPPED_TARGET}" "Projects" "${SUBJ_G}" '\Seen' "${SEEDED_EPOCH}"
	"${PYTHON_BIN}" "${SCRIPT_DIR}/../probe/stalwart.py" absent account "${MAPPED_SOURCE}"
	echo "absent: account ${MAPPED_SOURCE}, its mail merged into ${MAPPED_TARGET}"
fi
compose_mail "${BIBER_EMAIL}" "${STRAY}" "${SUBJ_S}"
send_smtp "127.0.0.1" "${BIBER_EMAIL}" "${STRAY}" "${SUBJ_S}"
wait_message "${STRAY}" "Projects" "${SUBJ_S}" "-" "-"
echo "sieve: the imported script is active and filed ${SUBJ_S} into Projects"

echo "=== [6/7] Re-run: nothing is imported twice ==="
run_migration "${MAILDIR_MOUNT}" "${WORKDIR}/import-2.log"
expect_line "${WORKDIR}/import-2.log" "[MAILBOX] ${STRAY} -> ${STRAY}: found=2 imported=0 skipped=2 failed=0 sieve=unchanged:projects"
wait_message "${STRAY}" "INBOX" "${SUBJ_E}" '\Seen' "${SEEDED_EPOCH}"
rm -rf "${MAILDIR_MOUNT:?}/${FOREIGN}"

echo "=== [7/7] Live flow in Stalwart (C: biber->admin, D: admin's reply) ==="
compose_mail "${BIBER_EMAIL}" "${ADMIN_EMAIL}" "${SUBJ_C}"
send_smtp "127.0.0.1" "${BIBER_EMAIL}" "${ADMIN_EMAIL}" "${SUBJ_C}"
compose_mail "${ADMIN_EMAIL}" "${BIBER_EMAIL}" "${SUBJ_D}" "${SUBJ_C}"
send_smtp "127.0.0.1" "${ADMIN_EMAIL}" "${BIBER_EMAIL}" "${SUBJ_D}"
wait_delivered "${ADMIN_EMAIL}" "${SUBJ_C}"
wait_delivered "${BIBER_EMAIL}" "${SUBJ_D}"

echo "MIGRATION STATE MACHINE COMPLETE"
