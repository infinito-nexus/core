#!/bin/bash
# set -u, not -e: the retry loop inspects msmtp's exit code explicitly, so a
# non-zero send must not abort the script on its own.
set -u
: "${MAIL_RECIPIENT:?MAIL_RECIPIENT not set}"
: "${MAIL_TIMEOUT:?MAIL_TIMEOUT not set}"
HOST="${HOSTNAME:-$(uname -n 2>/dev/null || echo unknown)}"

# The mail stack (mailu postfix/rspamd) briefly answers 451 "try again later"
# while it (re)starts during a deploy. Retry only those transient failures; any
# other exit code is a real fault and is propagated immediately, unmasked.
attempts=12
delay=12

for attempt in $(seq 1 "${attempts}"); do
  {
    echo "To: ${MAIL_RECIPIENT}"
    echo "Subject: ${HOST} is alive"
    echo
    echo "Host ${HOST} reports at $(date): I'm alive."
  } | timeout "${MAIL_TIMEOUT}"s msmtp -t
  rc=$?
  [ "${rc}" -eq 0 ] && exit 0

  # Retry ONLY on transient codes:
  #   69  EX_UNAVAILABLE - server temporarily unreachable or refused the
  #                        envelope; this is the 451 "try again later" we hit
  #                        while mailu is (re)starting.
  #   75  EX_TEMPFAIL    - msmtp's code for a temporary 4xx SMTP reply.
  #   124               - `timeout` killed the send (it exceeded MAIL_TIMEOUT;
  #                        the server hung instead of answering).
  # Anything else (e.g. 64 EX_USAGE, 78 EX_CONFIG, permanent 5xx rejects) is a
  # real error: exit now with that exact code instead of masking it with retries.
  case "${rc}" in
    69 | 75 | 124) ;;
    *) exit "${rc}" ;;
  esac

  if [ "${attempt}" -lt "${attempts}" ]; then
    echo "msmtp transient failure (rc=${rc}), attempt ${attempt}/${attempts}; retrying in ${delay}s" >&2
    sleep "${delay}"
  fi
done

exit "${rc}"
