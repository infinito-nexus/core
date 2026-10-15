#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

: "${PYTHON_BIN:?missing PYTHON_BIN}"
: "${MAIL_HOST:?missing MAIL_HOST}"
: "${NO_REPLY_EMAIL:?missing NO_REPLY_EMAIL}"
: "${NO_REPLY_SMTP_PASSWORD:?missing NO_REPLY_SMTP_PASSWORD}"

"${PYTHON_BIN}" "${SCRIPT_DIR}/probe_mail.py" relay \
	"${MAIL_HOST}" "${NO_REPLY_EMAIL}" "${NO_REPLY_SMTP_PASSWORD}"
echo "[relay] unauthenticated relay refused, ${NO_REPLY_EMAIL} submits authenticated"
