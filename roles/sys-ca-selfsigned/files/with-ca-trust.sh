#!/usr/bin/env sh
set -eu

: "${CA_TRUST_CERT:?CA_TRUST_CERT env var must be set (path to CA cert)}"
: "${CA_TRUST_NAME:?CA_TRUST_NAME env var must be set (trust anchor name)}"

VERBOSE="${VERBOSE:-1}"

# SPOT: system CA bundle candidates, in preference order
# (Debian/Ubuntu, RHEL/Fedora, Alpine/openssl default).
SYS_CA_BUNDLE_CANDIDATES="/etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt /etc/ssl/cert.pem"

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

# Sanitize trust name
name="$(printf '%s' "$CA_TRUST_NAME" | tr -c 'A-Za-z0-9._-' '_' )"
if [ -z "$name" ]; then
  echo "[with-ca-trust] ERROR: CA_TRUST_NAME resolved to empty after sanitization" >&2
  exit 4
fi

log "Sanitized trust name: $name"

installed=0

# Env-based trust fallback. Build a COMBINED bundle (system CAs + our CA) so the
# env vars don't break public-HTTPS validation; fall back to our CA only if no
# system bundle is found.
ca_bundle="$CA_TRUST_CERT"
combined="/tmp/with-ca-trust-combined.crt"
# shellcheck disable=SC2086 # intentional word-splitting; paths contain no spaces
for sys_bundle in $SYS_CA_BUNDLE_CANDIDATES; do
  if [ -r "$sys_bundle" ] && cat "$sys_bundle" "$CA_TRUST_CERT" > "$combined" 2>/dev/null; then
    ca_bundle="$combined"
    log "Combined system CA bundle ($sys_bundle) with ${name} -> $combined"
    break
  fi
done

export SSL_CERT_FILE="$ca_bundle"
export REQUESTS_CA_BUNDLE="$ca_bundle"
export CURL_CA_BUNDLE="$ca_bundle"
# Node already ships public roots; it only needs our CA appended.
export NODE_EXTRA_CA_CERTS="$CA_TRUST_CERT"

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

#
# Debian / Ubuntu style
#
if command -v update-ca-certificates >/dev/null 2>&1; then
  log "Detected update-ca-certificates"
  if install_anchor "$CA_TRUST_CERT" "/usr/local/share/ca-certificates/${name}.crt"; then
    run update-ca-certificates || true
  fi
fi

#
# RHEL / p11-kit style
#
if command -v update-ca-trust >/dev/null 2>&1; then
  log "Detected update-ca-trust"
  if install_anchor "$CA_TRUST_CERT" "/etc/pki/ca-trust/source/anchors/${name}.crt"; then
    run update-ca-trust extract || true
  fi
fi

#
# Arch / pure p11-kit style
#
if command -v trust >/dev/null 2>&1; then
  log "Detected trust"
  if install_anchor "$CA_TRUST_CERT" "/etc/ca-certificates/trust-source/anchors/${name}.crt"; then
    run trust extract-compat || true
  fi
fi

# ------------------------------------------------------------
# Chromium / NSS trust (per-user DB)
#
# Puppeteer/Chromium often uses NSS trust DB and may ignore OS CA store.
# Import the CA into the user's NSS DB if certutil is available.
#
# Requires:
#   - Debian/Ubuntu: apt-get install libnss3-tools
#   - Alpine: apk add nss-tools
# ------------------------------------------------------------
if command -v certutil >/dev/null 2>&1; then
  # Prefer real HOME; fall back to a writable temp dir
  home_dir="${HOME:-}"
  if [ -z "$home_dir" ] || [ ! -d "$home_dir" ] || [ ! -w "$home_dir" ]; then
    home_dir="/tmp"
  fi

  nss_db="${home_dir}/.pki/nssdb"
  log "Detected certutil; importing CA into NSS DB: ${nss_db}"

  # Ensure directory exists
  run mkdir -p "$nss_db" 2>/dev/null || true

  # Create NSS DB if missing (empty password)
  if [ ! -f "$nss_db/cert9.db" ]; then
    run certutil -N -d "sql:${nss_db}" --empty-password 2>/dev/null || true
  fi

  # Remove existing cert entry (best-effort)
  run certutil -D -d "sql:${nss_db}" -n "$name" >/dev/null 2>&1 || true

  # Import as trusted CA (C,, = trusted CA for SSL)
  run certutil -A -d "sql:${nss_db}" -n "$name" -t "C,," -i "$CA_TRUST_CERT" 2>/dev/null || true

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
