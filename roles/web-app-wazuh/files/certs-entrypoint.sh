#!/bin/bash
# Wazuh Docker Copyright (C) 2017, Wazuh Inc. (License GPLv2)
#
# Replaces wazuh/wazuh-certs-generator's own /entrypoint.sh (bind-mounted
# over it in templates/compose.yml.j2). The platform's shared
# ca-trust-wrapper (see docs/contributing/environment/cache.md and
# roles/sys-svc-compose/handlers/main.yml "Generate CA trust override")
# force-sets CURL_CA_BUNDLE/SSL_CERT_FILE/REQUESTS_CA_BUNDLE/
# NODE_EXTRA_CA_CERTS to the platform's own single-cert dev CA via a compose
# override file that is always merged AFTER this role's own compose.yml, so
# an `environment:` override in compose.yml.j2 is silently clobbered
# (confirmed empirically against a live deploy). This container's original
# entrypoint downloads its cert-generation tool from the genuinely-public
# internet (packages.wazuh.com), which a single-cert CURL_CA_BUNDLE cannot
# verify. `unset` here restores curl's default trust store, which the
# wrapper's own `update-ca-trust extract` step has already populated with
# both the system's public CAs and the platform's dev CA. Everything below
# this point is an unmodified copy of the vendor's own /entrypoint.sh.
unset CURL_CA_BUNDLE SSL_CERT_FILE REQUESTS_CA_BUNDLE NODE_EXTRA_CA_CERTS

CERT_TOOL=wazuh-certs-tool.sh
# shellcheck disable=SC2034 # unmodified vendor logic
PASSWORD_TOOL=wazuh-passwords-tool.sh
PACKAGES_URL=https://packages.wazuh.com/$CERT_TOOL_VERSION/
PACKAGES_DEV_URL=https://packages-dev.wazuh.com/$CERT_TOOL_VERSION/

OUTPUT_FILE="/$CERT_TOOL"

download_package() {
    local url=$1
    echo "Checking $url$CERT_TOOL ..."
    if curl -fsL "$url$CERT_TOOL" -o "$OUTPUT_FILE"; then
        echo "Downloaded $CERT_TOOL from $url"
        return 0
    else
        return 1
    fi
}

if download_package "$PACKAGES_URL"; then
    :
elif download_package "$PACKAGES_DEV_URL"; then
    echo "WARNING: $CERT_TOOL was not found on the stable bucket ($PACKAGES_URL)." >&2
    echo "WARNING: falling back to the dev bucket ($PACKAGES_DEV_URL), which is unversioned/unstable upstream." >&2
else
    echo "The tool to create the certificates does not exist in any bucket"
    echo "ERROR: certificates were not created"
    exit 1
fi

cp /config/certs.yml /config.yml
chmod 700 "$OUTPUT_FILE"

# shellcheck disable=SC1090 # unmodified vendor logic; CERT_TOOL is a fixed, known filename
source /$CERT_TOOL -A
nodes_server=$( cert_parseYaml /config.yml | grep -E "nodes[_]+server[_]+[0-9]+=" | sed -e 's/nodes__server__[0-9]=//' | sed 's/"//g' )
# shellcheck disable=SC2206 # unmodified vendor logic; node names are always simple hostnames, never contain spaces/globs
node_names=($nodes_server)

echo "Moving created certificates to the destination directory"
cp /wazuh-certificates/* /certificates/
echo "Changing certificate permissions"
chmod -R 500 /certificates
chmod -R 400 /certificates/*
echo "Setting UID indexer and dashboard"
chown 1000:1000 /certificates/*
echo "Setting UID for wazuh manager and worker"
cp /certificates/root-ca.pem /certificates/root-ca-manager.pem
cp /certificates/root-ca.key /certificates/root-ca-manager.key
chown 999:999 /certificates/root-ca-manager.pem
chown 999:999 /certificates/root-ca-manager.key

# shellcheck disable=SC2068 # unmodified vendor logic; node names are always simple hostnames, never contain spaces/globs
for i in ${node_names[@]};
do
  chown 999:999 "/certificates/${i}.pem"
  chown 999:999 "/certificates/${i}-key.pem"
done
