#!/usr/bin/env bash
if [ -n "${CA_TRUST_CERT:-}" ] && [ -r "${CA_TRUST_CERT}" ]; then
  CACERTS="/usr/share/wazuh-indexer/jdk/lib/security/cacerts"
  ALIAS="${CA_TRUST_NAME:?CA_TRUST_NAME must accompany CA_TRUST_CERT}"
  KEYTOOL="/usr/share/wazuh-indexer/jdk/bin/keytool"
  if ! "$KEYTOOL" -list -keystore "$CACERTS" -storepass changeit -alias "$ALIAS" >/dev/null 2>&1; then
    "$KEYTOOL" -importcert -noprompt -alias "$ALIAS" -file "$CA_TRUST_CERT" -keystore "$CACERTS" -storepass changeit
  fi
fi

exec /entrypoint.sh "$@"
