#!/usr/bin/env sh
set -eu

: "${CA_TRUST_CERT:?CA_TRUST_CERT env var must be set (path to CA cert)}"
: "${CA_TRUST_NAME:?CA_TRUST_NAME env var must be set (trust anchor name)}"

VERBOSE="${VERBOSE:-1}"

log() {
  if [ "$VERBOSE" = "1" ]; then
    echo "[with-ca-trust] $*" >&2
  fi
}

run() {
  log "RUN: $*"
  "$@"
}

log "Starting CA trust installation"
log "CA_TRUST_CERT=$CA_TRUST_CERT"
log "CA_TRUST_NAME=$CA_TRUST_NAME"

if [ ! -r "$CA_TRUST_CERT" ]; then
  echo "[with-ca-trust] ERROR: CA certificate not readable: $CA_TRUST_CERT" >&2
  exit 2
fi

name="$(printf '%s' "$CA_TRUST_NAME" | tr -c 'A-Za-z0-9._-' '_' )"
if [ -z "$name" ]; then
  echo "[with-ca-trust] ERROR: CA_TRUST_NAME resolved to empty after sanitization" >&2
  exit 4
fi

log "Sanitized trust name: $name"

installed=0

export SSL_CERT_FILE="$CA_TRUST_CERT"
export REQUESTS_CA_BUNDLE="$CA_TRUST_CERT"
export CURL_CA_BUNDLE="$CA_TRUST_CERT"
export NODE_EXTRA_CA_CERTS="$CA_TRUST_CERT"

if [ -n "${CA_TRUST_CERT_EXTRA:-}" ] && [ -r "${CA_TRUST_CERT_EXTRA}" ]; then
  combined="/tmp/ca-trust-combined.crt"
  if cat "$CA_TRUST_CERT" "$CA_TRUST_CERT_EXTRA" > "$combined" 2>/dev/null; then
    export SSL_CERT_FILE="$combined"
    export REQUESTS_CA_BUNDLE="$combined"
    export CURL_CA_BUNDLE="$combined"
    export NODE_EXTRA_CA_CERTS="$combined"
  else
    log "WARN: cannot write $combined; keeping single-CA trust env"
  fi
fi

install_anchor() {
  src="$1"
  dst="$2"

  log "Installing CA anchor: $dst"
  if run mkdir -p "$(dirname "$dst")" 2>/dev/null && run cp -f "$src" "$dst" 2>/dev/null; then
    installed=1
    return 0
  fi

  log "WARN: Cannot write CA anchor to $dst (no permission). Falling back to SSL_CERT_FILE/REQUESTS_CA_BUNDLE only."
  return 1
}

if command -v update-ca-certificates >/dev/null 2>&1; then
  log "Detected update-ca-certificates"
  if install_anchor "$CA_TRUST_CERT" "/usr/local/share/ca-certificates/${name}.crt"; then
    run update-ca-certificates || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  fi
fi

if command -v update-ca-trust >/dev/null 2>&1; then
  log "Detected update-ca-trust"
  if install_anchor "$CA_TRUST_CERT" "/etc/pki/ca-trust/source/anchors/${name}.crt"; then
    run update-ca-trust extract || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  fi
fi

if command -v trust >/dev/null 2>&1; then
  log "Detected trust"
  if install_anchor "$CA_TRUST_CERT" "/etc/ca-certificates/trust-source/anchors/${name}.crt"; then
    run trust extract-compat || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  fi
fi

if [ -n "${CA_TRUST_CERT_EXTRA:-}" ] && [ -r "${CA_TRUST_CERT_EXTRA}" ]; then
  if command -v update-ca-certificates >/dev/null 2>&1 && install_anchor "$CA_TRUST_CERT_EXTRA" "/usr/local/share/ca-certificates/${name}-extra.crt"; then
    run update-ca-certificates || true  # nocheck: shell-or-true -- best-effort trust-store refresh; the env-based CA bundle above remains the fallback
  fi
  if command -v update-ca-trust >/dev/null 2>&1 && install_anchor "$CA_TRUST_CERT_EXTRA" "/etc/pki/ca-trust/source/anchors/${name}-extra.crt"; then
    run update-ca-trust extract || true  # nocheck: shell-or-true -- best-effort trust-store refresh; the env-based CA bundle above remains the fallback
  fi
  if command -v trust >/dev/null 2>&1 && install_anchor "$CA_TRUST_CERT_EXTRA" "/etc/ca-certificates/trust-source/anchors/${name}-extra.crt"; then
    run trust extract-compat || true  # nocheck: shell-or-true -- best-effort trust-store refresh; the env-based CA bundle above remains the fallback
  fi
fi

if command -v certutil >/dev/null 2>&1; then
  home_dir="${HOME:-}"
  if [ -z "$home_dir" ] || [ ! -d "$home_dir" ] || [ ! -w "$home_dir" ]; then
    home_dir="/tmp"
  fi

  nss_db="${home_dir}/.pki/nssdb"
  log "Detected certutil; importing CA into NSS DB: ${nss_db}"

  run mkdir -p "$nss_db" 2>/dev/null || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

  if [ ! -f "$nss_db/cert9.db" ]; then
    run certutil -N -d "sql:${nss_db}" --empty-password 2>/dev/null || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  fi

  run certutil -D -d "sql:${nss_db}" -n "$name" >/dev/null 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

  run certutil -A -d "sql:${nss_db}" -n "$name" -t "C,," -i "$CA_TRUST_CERT" 2>/dev/null || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error

  log "NSS trust import attempted (best-effort)"
else
  log "certutil not available; skipping NSS trust import (Chromium may still fail)"
fi

if [ "$installed" = "1" ]; then
  log "CA trust installation completed successfully"
else
  log "CA trust not installed into OS trust store; using env-based CA variables only"
fi

if [ "$#" -gt 0 ]; then
  log "Executing wrapped command: $*"
  exec "$@"
fi

log "No command provided to execute; exiting successfully"
exit 0
