#!/usr/bin/env bash
set -euo pipefail

unset CURL_CA_BUNDLE SSL_CERT_FILE REQUESTS_CA_BUNDLE NODE_EXTRA_CA_CERTS

: "${CERT_TOOL_VERSION:?CERT_TOOL_VERSION must name the wazuh-certs-tool release}"
: "${WAZUH_MANAGER_NODE:?WAZUH_MANAGER_NODE must name the manager node in /config/certs.yml}"

config_src="/config/certs.yml"
out_dir="/certificates"
tool_url="https://packages.wazuh.com/${CERT_TOOL_VERSION}/wazuh-certs-tool.sh"

work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT

if ! curl --connect-timeout 10 --max-time 120 --fail --silent --show-error --location \
  --retry 5 --retry-delay 5 --retry-all-errors \
  --output "${work_dir}/wazuh-certs-tool.sh" "${tool_url}"; then
  echo "ERROR: downloading ${tool_url} failed; no certificates were generated" >&2
  exit 1
fi

cp "${config_src}" "${work_dir}/config.yml"
bash "${work_dir}/wazuh-certs-tool.sh" --all

cp "${work_dir}"/wazuh-certificates/* "${out_dir}/"
cp "${out_dir}/root-ca.pem" "${out_dir}/root-ca-manager.pem"
cp "${out_dir}/root-ca.key" "${out_dir}/root-ca-manager.key"

chmod 0400 "${out_dir}"/*
chown 1000:1000 "${out_dir}"/*
chown 999:999 \
  "${out_dir}/root-ca-manager.pem" \
  "${out_dir}/root-ca-manager.key" \
  "${out_dir}/${WAZUH_MANAGER_NODE}.pem" \
  "${out_dir}/${WAZUH_MANAGER_NODE}-key.pem"
chmod 0500 "${out_dir}"

echo "Wazuh certificates written to ${out_dir}"
