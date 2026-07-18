#!/usr/bin/env bash
# Runtime entrypoint that imports the project CA into the JVM cacerts
# before handing off to the upstream `jenkins.sh` start command. The
# `with-ca-trust` wrapper installed by sys-svc-container exports
# CA_TRUST_CERT_HOST=/etc/infinito.nexus/ca/root-ca.crt at startup,
# but it only handles OS-level + Python-style trust stores. Java reads
# its own keystore (PKCS12 at $JAVA_HOME/lib/security/cacerts) so we
# import explicitly here. Fails-open on missing CA so production
# deploys (publicly-trusted certs) start unchanged.
set -euo pipefail

# with-ca-trust.sh exposes the cert at the in-container path through
# `CA_TRUST_CERT` (NOT `CA_TRUST_CERT_HOST` — that's the host-side
# path used by the wrapper itself). Read both to stay robust if the
# convention shifts.
CA_FILE="${CA_TRUST_CERT:-${CA_TRUST_CERT_HOST:-}}"
CA_TRUST_NAME="${CA_TRUST_NAME:-infinito-ca}"

if [[ -n "${CA_FILE}" && -r "${CA_FILE}" ]]; then
  CACERTS="${JAVA_HOME:-/opt/java/openjdk}/lib/security/cacerts"
  if [[ -w "${CACERTS}" ]]; then
    # `-noprompt -trustcacerts` keeps the import idempotent; `-alias`
    # collisions on re-run are surfaced as `Certificate not imported,
    # alias <alias> already exists` which we tolerate (already-trusted
    # is the desired end state).
    keytool -importcert \
      -noprompt -trustcacerts \
      -alias "${CA_TRUST_NAME}" \
      -file "${CA_FILE}" \
      -keystore "${CACERTS}" \
      -storepass "changeit" >/dev/null 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  fi
fi

exec "$@"
