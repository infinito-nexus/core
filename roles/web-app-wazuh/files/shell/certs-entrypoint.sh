#!/usr/bin/env bash
set -euo pipefail

unset CURL_CA_BUNDLE SSL_CERT_FILE REQUESTS_CA_BUNDLE NODE_EXTRA_CA_CERTS

: "${CERT_TOOL_VERSION:?CERT_TOOL_VERSION must name the wazuh-certs-tool release}"
: "${WAZUH_MANAGER_NODE:?WAZUH_MANAGER_NODE must name the manager node in the certs config}"
: "${CERTS_CONFIG:?CERTS_CONFIG must point at the mounted certs.yml}"
: "${CERTS_OUT_DIR:?CERTS_OUT_DIR must point at the mounted certificates directory}"
: "${CERTS_MIN_VALID_DAYS:?CERTS_MIN_VALID_DAYS must give the days a certificate must still be valid to be kept}"
: "${CERTS_MARKER:?CERTS_MARKER must point at the generation marker inside CERTS_OUT_DIR}"
: "${CERTS_OWNER:?CERTS_OWNER must give the uid:gid of the indexer and dashboard}"
: "${CERTS_MANAGER_OWNER:?CERTS_MANAGER_OWNER must give the uid:gid of the manager}"

config_src="${CERTS_CONFIG}"
out_dir="${CERTS_OUT_DIR}"
marker="${CERTS_MARKER}"
tool_url="https://packages.wazuh.com/${CERT_TOOL_VERSION}/wazuh-certs-tool.sh"

expected_marker() {
	printf '%s %s\n' "$(sha256sum "${config_src}" | cut -d' ' -f1)" "${CERT_TOOL_VERSION}"
}

pubkey_of_cert() {
	openssl x509 -in "$1" -noout -pubkey
}

pubkey_of_key() {
	openssl pkey -in "$1" -pubout
}

stale_reason() {
	local name cert key min_valid_s
	min_valid_s=$((CERTS_MIN_VALID_DAYS * 86400))
	if [[ ! -s "${marker}" ]] || [[ "$(cat "${marker}")" != "$(expected_marker)" ]]; then
		echo "the certs config or the tool version changed since the last generation"
		return
	fi
	for name in root-ca root-ca-manager; do
		if [[ ! -s "${out_dir}/${name}.pem" || ! -s "${out_dir}/${name}.key" ]]; then
			echo "${name}.pem or ${name}.key is missing or empty"
			return
		fi
	done
	for name in admin $(sed -nE 's/^[[:space:]]*-[[:space:]]*name:[[:space:]]*([^[:space:]]+).*$/\1/p' "${config_src}"); do
		cert="${out_dir}/${name}.pem"
		key="${out_dir}/${name}-key.pem"
		if [[ ! -s "${cert}" || ! -s "${key}" ]]; then
			echo "${name}.pem or ${name}-key.pem is missing or empty"
			return
		fi
		if ! openssl verify -CAfile "${out_dir}/root-ca.pem" "${cert}" >/dev/null 2>&1; then
			echo "${name}.pem does not verify against root-ca.pem"
			return
		fi
		if ! openssl x509 -in "${cert}" -noout -checkend "${min_valid_s}" >/dev/null; then
			echo "${name}.pem expires within ${CERTS_MIN_VALID_DAYS} days"
			return
		fi
		if [[ "$(pubkey_of_cert "${cert}")" != "$(pubkey_of_key "${key}")" ]]; then
			echo "${name}-key.pem does not match ${name}.pem"
			return
		fi
	done
	if ! openssl x509 -in "${out_dir}/root-ca.pem" -noout -checkend "${min_valid_s}" >/dev/null; then
		echo "root-ca.pem expires within ${CERTS_MIN_VALID_DAYS} days"
		return
	fi
	if [[ "$(pubkey_of_cert "${out_dir}/root-ca.pem")" != "$(pubkey_of_key "${out_dir}/root-ca.key")" ]]; then
		echo "root-ca.key does not match root-ca.pem"
		return
	fi
}

reason="$(stale_reason)"
if [[ -z "${reason}" ]]; then
	echo "Wazuh certificates in ${out_dir} are current; skipping generation"
	exit 0
fi
echo "Regenerating Wazuh certificates: ${reason}"

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
chown "${CERTS_OWNER}" "${out_dir}"/*
chown "${CERTS_MANAGER_OWNER}" \
	"${out_dir}/root-ca-manager.pem" \
	"${out_dir}/root-ca-manager.key" \
	"${out_dir}/${WAZUH_MANAGER_NODE}.pem" \
	"${out_dir}/${WAZUH_MANAGER_NODE}-key.pem"
expected_marker >"${marker}"
chmod 0400 "${marker}"
chmod 0500 "${out_dir}"

echo "Wazuh certificates written to ${out_dir}"
