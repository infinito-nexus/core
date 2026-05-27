#!/bin/bash
set -eu
: "${MAIL_RECIPIENT:?MAIL_RECIPIENT not set}"
: "${MAIL_TIMEOUT:?MAIL_TIMEOUT not set}"
{
  echo "To: ${MAIL_RECIPIENT}"
  echo "Subject: $(hostname) is alive"
  echo
  echo "Host $(hostname) reports at $(date): I'm alive."
} | timeout "${MAIL_TIMEOUT}"s msmtp -t
