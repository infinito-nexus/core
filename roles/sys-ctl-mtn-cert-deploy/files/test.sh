#!/bin/sh
set -eu

# Validates deployed TLS certificates.
#
# Local mode (argument): checks the cert material script.sh deployed into a
# compose instance directory — cert.pem/key.pem exist, parse, match each
# other, and are not about to expire.
#
# Remote mode (environment): checks live TLS endpoints, e.g. production
# servers, so a misconfigured host surfaces in CI instead of in an outage.
#
# Usage:
#   test.sh [<docker_compose_instance_directory>]
#
# Environment:
#   CERT_TEST_REMOTE_ENDPOINTS  Space-separated "host[:port]" list (port
#                               defaults to 443). Intended to be fed from a
#                               CI/GitHub variable.
#   CERT_TEST_MIN_DAYS          Minimum remaining validity in days (default 14).
#
# At least one mode must be selected. Exit code is non-zero on any failure.

min_days="${CERT_TEST_MIN_DAYS:-14}"
min_seconds=$((min_days * 86400))
failures=0

fail() {
  echo "FAIL: $*" >&2
  failures=$((failures + 1))
}

check_local() {
  instance_dir="$1"
  cert_dir="${instance_dir%/}/volumes/certs"
  cert="${cert_dir}/cert.pem"
  key="${cert_dir}/key.pem"

  echo "Checking deployed certificate in: $cert_dir"

  if [ ! -r "$cert" ] || [ ! -r "$key" ]; then
    fail "cert.pem/key.pem missing or unreadable in $cert_dir"
    return
  fi

  if ! openssl x509 -in "$cert" -noout 2>/dev/null; then
    fail "$cert does not parse as an X.509 certificate"
    return
  fi

  # Public-key comparison works for RSA and EC alike (modulus does not).
  cert_pub="$(openssl x509 -in "$cert" -pubkey -noout 2>/dev/null)"
  key_pub="$(openssl pkey -in "$key" -pubout 2>/dev/null)"
  if [ -z "$key_pub" ] || [ "$cert_pub" != "$key_pub" ]; then
    fail "key.pem does not match cert.pem in $cert_dir"
  fi

  if ! openssl x509 -in "$cert" -noout -checkend "$min_seconds" >/dev/null; then
    fail "$cert expires within ${min_days} days"
  else
    echo "OK: $cert valid, key matches, >= ${min_days} days remaining"
  fi
}

check_remote() {
  endpoint="$1"
  host="${endpoint%%:*}"
  port="${endpoint#*:}"
  [ "$port" = "$host" ] && port=443

  echo "Checking remote endpoint: ${host}:${port}"

  probe="$(printf '' | openssl s_client -connect "${host}:${port}" \
    -servername "$host" -verify_hostname "$host" 2>/dev/null)" || {
    fail "${host}:${port} TLS handshake failed"
    return
  }

  if ! printf '%s\n' "$probe" | grep -q "Verify return code: 0 (ok)"; then
    code="$(printf '%s\n' "$probe" | sed -n 's/^ *Verify return code: //p' | head -n1)"
    fail "${host}:${port} certificate verification failed (${code:-no verify result})"
    return
  fi

  if ! printf '%s\n' "$probe" | openssl x509 -noout -checkend "$min_seconds" >/dev/null 2>&1; then
    fail "${host}:${port} certificate expires within ${min_days} days"
  else
    echo "OK: ${host}:${port} chain verified, >= ${min_days} days remaining"
  fi
}

ran_any=0

if [ "$#" -ge 1 ]; then
  ran_any=1
  check_local "$1"
fi

if [ -n "${CERT_TEST_REMOTE_ENDPOINTS:-}" ]; then
  ran_any=1
  for endpoint in $CERT_TEST_REMOTE_ENDPOINTS; do
    check_remote "$endpoint"
  done
fi

if [ "$ran_any" = "0" ]; then
  echo "Usage: $0 [<docker_compose_instance_directory>]" >&2
  echo "Set CERT_TEST_REMOTE_ENDPOINTS=\"host[:port] ...\" for remote checks." >&2
  exit 1
fi

if [ "$failures" -gt 0 ]; then
  echo "Certificate test finished with ${failures} failure(s)." >&2
  exit 1
fi

echo "Certificate test passed."
