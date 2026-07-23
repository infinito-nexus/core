#!/bin/bash
set -u
: "${MAIL_RECIPIENT:?MAIL_RECIPIENT not set}"
: "${MAIL_TIMEOUT:?MAIL_TIMEOUT not set}"
HOST="${HOSTNAME:-$(uname -n 2>/dev/null || echo unknown)}"

attempts=12
delay=12

for attempt in $(seq 1 "${attempts}"); do
  msmtp_err="$(
    {
      echo "To: ${MAIL_RECIPIENT}"
      echo "Subject: ${HOST} is alive"
      echo
      echo "Host ${HOST} reports at $(date): I'm alive."
    } | timeout "${MAIL_TIMEOUT}"s msmtp -t 2>&1 1>/dev/null
  )"
  rc=$?
  [ "${rc}" -eq 0 ] && exit 0

  case "${rc}" in
    69 | 75 | 124) ;;
    77)
      case "${msmtp_err}" in
        *454* | *"Temporary authentication failure"*) ;;
        *) exit "${rc}" ;;
      esac
      ;;
    *) exit "${rc}" ;;
  esac

  if [ "${attempt}" -lt "${attempts}" ]; then
    echo "msmtp transient failure (rc=${rc}), attempt ${attempt}/${attempts}; retrying in ${delay}s" >&2
    sleep "${delay}"
  fi
done

exit "${rc}"
