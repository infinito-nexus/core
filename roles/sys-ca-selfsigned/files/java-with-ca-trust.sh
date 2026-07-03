#!/usr/bin/env bash
# Entrypoint wrapper: import the project root CA into the JVM truststore, then
# exec the real command. Reads the in-container cert from CA_TRUST_CERT (set by
# sys-svc-compose-ca under self_signed TLS). No cert present means a production
# deploy with publicly trusted certs: exec through unchanged. With a cert
# present the import MUST succeed; a broken JVM trust chain would otherwise
# surface much later as an opaque PKIX failure on the first OIDC call.
# Writable cacerts are patched in place; read-only layouts get a /tmp copy
# activated via JAVA_TOOL_OPTIONS.
set -euo pipefail

CA_FILE="${CA_TRUST_CERT:-}"
CA_ALIAS="${CA_TRUST_NAME:-infinito-ca}"

if [ -z "${CA_FILE}" ] || [ ! -r "${CA_FILE}" ]; then
	exec "$@"
fi

JAVA_DIR=""
for candidate in "${JAVA_HOME:-}" /opt/jre /opt/jdk /opt/java/openjdk; do
	[ -n "${candidate}" ] || continue
	if [ -r "${candidate}/lib/security/cacerts" ]; then
		JAVA_DIR="${candidate}"
		break
	fi
done
if [ -z "${JAVA_DIR}" ]; then
	echo "java-with-ca-trust: FATAL no JRE cacerts found (JAVA_HOME, /opt/jre, /opt/jdk, /opt/java/openjdk)" >&2
	exit 90
fi

KEYTOOL="${JAVA_DIR}/bin/keytool"
if [ ! -x "${KEYTOOL}" ]; then
	KEYTOOL="$(command -v keytool || true)"
fi
if [ -z "${KEYTOOL}" ]; then
	echo "java-with-ca-trust: FATAL keytool not found" >&2
	exit 91
fi

CACERTS="${JAVA_DIR}/lib/security/cacerts"
if [ -w "${CACERTS}" ]; then
	"${KEYTOOL}" -importcert -noprompt -trustcacerts -alias "${CA_ALIAS}" \
		-file "${CA_FILE}" -keystore "${CACERTS}" -storepass changeit >/dev/null 2>&1 || true
	"${KEYTOOL}" -list -keystore "${CACERTS}" -storepass changeit -alias "${CA_ALIAS}" >/dev/null
else
	rm -f /tmp/cacerts
	cp "${CACERTS}" /tmp/cacerts
	chmod u+w /tmp/cacerts
	"${KEYTOOL}" -importcert -noprompt -trustcacerts -alias "${CA_ALIAS}" \
		-file "${CA_FILE}" -keystore /tmp/cacerts -storepass changeit >/dev/null
	"${KEYTOOL}" -list -keystore /tmp/cacerts -storepass changeit -alias "${CA_ALIAS}" >/dev/null
	export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:-} -Djavax.net.ssl.trustStore=/tmp/cacerts -Djavax.net.ssl.trustStorePassword=changeit"
fi

exec "$@"
