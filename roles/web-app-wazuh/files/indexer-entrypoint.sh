#!/usr/bin/env bash
# Wazuh Docker Copyright (C) 2017, Wazuh Inc. (License GPLv2)
#
# --- infinito.nexus addition -------------------------------------------
# The platform's shared CA-trust injection (compose.ca.override.yml) only
# sets CURL_CA_BUNDLE/SSL_CERT_FILE/REQUESTS_CA_BUNDLE/NODE_EXTRA_CA_CERTS -
# none of which the JVM honours. wazuh.indexer's own OIDC authenticator
# (config.yml's openid_auth_domain) makes an outbound HTTPS call from
# inside the JVM to Keycloak's discovery/JWKS endpoint to validate ID
# tokens; without the platform's dev CA in the JVM's own cacerts keystore,
# that call fails with PKIX path building failed / AuthenticatorUnavailableException,
# which OpenSearch Security surfaces to the dashboard as a bare
# "Authentication Exception" - confirmed against a live deploy by reading
# the indexer's own stack trace. keytool import is the only fix; there is
# no env-var-based shortcut for the JVM trust store. This must run before
# the privilege-drop below, since the cacerts file is not writable by the
# unprivileged wazuh-indexer user.
#
# No hardcoded path fallback here (unlike an earlier revision): CA_TRUST_CERT
# is always set by the platform's compose.ca.override.yml when CA injection
# is active, matching the guard-only pattern already used by
# web-app-pixelfed/files/docker-entrypoint.sh and
# web-app-jenkins/files/entrypoint-with-ca.sh. This also means the container
# path this value points at (currently /tmp/infinito/ca/root-ca.crt) has no
# duplicate literal to update if the platform's own SPOT for it changes.
if [ -n "${CA_TRUST_CERT:-}" ] && [ -r "${CA_TRUST_CERT}" ]; then
  CACERTS="/usr/share/wazuh-indexer/jdk/lib/security/cacerts"
  ALIAS="${CA_TRUST_NAME:-infinito-dev-ca}"
  KEYTOOL="/usr/share/wazuh-indexer/jdk/bin/keytool"
  if ! "$KEYTOOL" -list -keystore "$CACERTS" -storepass changeit -alias "$ALIAS" >/dev/null 2>&1; then
    "$KEYTOOL" -importcert -noprompt -alias "$ALIAS" -file "$CA_TRUST_CERT" -keystore "$CACERTS" -storepass changeit
  fi
fi
# --- end infinito.nexus addition ----------------------------------------

set -e

umask 0002

export USER=wazuh-indexer
export INSTALLATION_DIR=/usr/share/wazuh-indexer
export OPENSEARCH_PATH_CONF=${INSTALLATION_DIR}/config
export JAVA_HOME=${INSTALLATION_DIR}/jdk
# shellcheck disable=SC2155 # unmodified vendor logic
export DISCOVERY=$(grep -oP "(?<=discovery.type: ).*" ${OPENSEARCH_PATH_CONF}/opensearch.yml)
# shellcheck disable=SC2155 # unmodified vendor logic
export CACERT=$(grep -oP "(?<=plugins.security.ssl.transport.pemtrustedcas_filepath: ).*" ${OPENSEARCH_PATH_CONF}/opensearch.yml)
export CERT="${OPENSEARCH_PATH_CONF}/certs/admin.pem"
export KEY="${OPENSEARCH_PATH_CONF}/certs/admin-key.pem"

run_as_other_user_if_needed() {
  if [[ "$(id -u)" == "0" ]]; then
    # If running as root, drop to specified UID and run command
    exec chroot --userspec=1000:0 / "${@}"
  else
    # Either we are running in Openshift with random uid and are a member of the root group
    # or with a custom --user
    exec "${@}"
  fi
}

# Allow user specify custom CMD, maybe bin/opensearch itself
# for example to directly specify `-E` style parameters for opensearch on k8s
# or simply to run /bin/bash to check the image
if [[ "$1" != "opensearchwrapper" ]]; then
  if [[ "$(id -u)" == "0" && $(basename "$1") == "opensearch" ]]; then
    # Rewrite CMD args to replace $1 with `opensearch` explicitly,
    # Without this, user could specify `opensearch -E x.y=z` but
    # `bin/opensearch -E x.y=z` would not work.
    set -- "opensearch" "${@:2}"
    # Use chroot to switch to UID 1000 / GID 0
    exec chroot --userspec=1000:0 / "$@"
  else
    # User probably wants to run something else, like /bin/bash, with another uid forced (Openshift?)
    exec "$@"
  fi
fi

# Allow environment variables to be set by creating a file with the
# contents, and setting an environment variable with the suffix _FILE to
# point to it. This can be used to provide secrets to a container, without
# the values being specified explicitly when running the container.
#
# This is also sourced in opensearch-env, and is only needed here
# as well because we use INDEXER_PASSWORD below. Sourcing this script
# is idempotent.
# shellcheck disable=SC1091 # unmodified vendor logic; file only exists inside the real image
source /usr/share/wazuh-indexer/bin/opensearch-env-from-file

if [[ -f bin/opensearch-users ]]; then
  # Check for the INDEXER_PASSWORD environment variable to set the
  # bootstrap password for Security.
  #
  # This is only required for the first node in a cluster with Security
  # enabled, but we have no way of knowing which node we are yet. We'll just
  # honor the variable if it's present.
  if [[ -n "$INDEXER_PASSWORD" ]]; then
    [[ -f /usr/share/wazuh-indexer/opensearch.keystore ]] || (run_as_other_user_if_needed opensearch-keystore create)
    if ! (run_as_other_user_if_needed opensearch-keystore has-passwd --silent) ; then
      # keystore is unencrypted
      if ! (run_as_other_user_if_needed opensearch-keystore list | grep -q '^bootstrap.password$'); then
        (run_as_other_user_if_needed echo "$INDEXER_PASSWORD" | opensearch-keystore add -x 'bootstrap.password')
      fi
    else
      # keystore requires password
      if ! (run_as_other_user_if_needed echo "$KEYSTORE_PASSWORD" \
          | opensearch-keystore list | grep -q '^bootstrap.password$') ; then
        COMMANDS="$(printf "%s\n%s" "$KEYSTORE_PASSWORD" "$INDEXER_PASSWORD")"
        (run_as_other_user_if_needed echo "$COMMANDS" | opensearch-keystore add -x 'bootstrap.password')
      fi
    fi
  fi
fi

if [[ "$(id -u)" == "0" ]]; then
  # If requested and running as root, mutate the ownership of bind-mounts
  if [[ -n "$TAKE_FILE_OWNERSHIP" ]]; then
    chown -R 1000:0 /usr/share/wazuh-indexer/{data,logs}
  fi
fi


#if [[ "$DISCOVERY" == "single-node" ]] && [[ ! -f "/var/lib/wazuh-indexer/.flag" ]]; then
  # run securityadmin.sh for single node with CACERT, CERT and KEY parameter
#  nohup /securityadmin.sh &
#  touch "/var/lib/wazuh-indexer/.flag"
#fi

run_as_other_user_if_needed /usr/share/wazuh-indexer/bin/opensearch <<<"$KEYSTORE_PASSWORD"
