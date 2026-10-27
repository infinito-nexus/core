#!/usr/bin/env bash
# Print the registry proxy of the stack's docker daemon as JSON; every value is empty when it has none.
set -euo pipefail

env_line="$(systemctl show docker.service -p Environment --value)"
pre_line="$(systemctl show docker.service -p ExecStartPre --value)"
proxy="$(tr ' ' '\n' <<<"${env_line}" | sed -n 's/^HTTPS_PROXY=//p')"
no_proxy="$(tr ' ' '\n' <<<"${env_line}" | sed -n 's/^NO_PROXY=//p')"
host=""
ip=""
mitm_ca=false
if [ -n "${proxy}" ]; then
	host="$(sed -E 's#^[a-z]+://([^:/]+).*#\1#' <<<"${proxy}")"
	ip="$(getent hosts "${host}" | awk '{print $1; exit}')"
	if grep -q 'registry-cache-ca' <<<"${pre_line}"; then
		mitm_ca=true
	fi
fi
printf '{"proxy":"%s","no_proxy":"%s","host":"%s","ip":"%s","mitm_ca":%s}\n' \
	"${proxy}" "${no_proxy}" "${host}" "${ip}" "${mitm_ca}"
