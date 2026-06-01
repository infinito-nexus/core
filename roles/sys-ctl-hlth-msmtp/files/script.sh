#!/bin/bash
set -eu
: "${MAIL_RECIPIENT:?MAIL_RECIPIENT not set}"
: "${MAIL_TIMEOUT:?MAIL_TIMEOUT not set}"
HOST="${HOSTNAME:-$(uname -n 2>/dev/null || echo unknown)}"
{
  echo "To: ${MAIL_RECIPIENT}"
  echo "Subject: ${HOST} is alive"
  echo
  echo "Host ${HOST} reports at $(date): I'm alive."
} | timeout "${MAIL_TIMEOUT}"s msmtp -t
