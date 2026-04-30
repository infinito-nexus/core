#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------
# Load environment (Single Source of Truth)
# ------------------------------------------------------------
ENV_FILE="${ENV_FILE:-env.ci}"

if [ ! -f "${ENV_FILE}" ]; then
	echo "ERROR: env file not found: ${ENV_FILE}"
	exit 1
fi

# Export all variables from env file
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

# Source project defaults so INFINITO_CONTAINER auto-derives from
# INFINITO_DISTRO (single SPOT in scripts/meta/env/defaults.sh) — callers
# only need to set INFINITO_DISTRO.
# shellcheck source=scripts/meta/env/defaults.sh
source scripts/meta/env/defaults.sh

# ------------------------------------------------------------
# Required variables (fail hard if missing)
# ------------------------------------------------------------
: "${DNS_IP:?Missing DNS_IP in env file}"
: "${DOMAIN:?Missing DOMAIN in env file}"
: "${IP4:?Missing IP4 in env file}"
: "${INFINITO_CONTAINER:?Missing INFINITO_CONTAINER env (e.g. infinito_nexus_arch)}"

SUBDOMAIN="foo.${DOMAIN}"
IP4_EXPECTED="${IP4}"

# ------------------------------------------------------------
# Output helpers
# ------------------------------------------------------------
section() {
	echo
	echo "------------------------------------------------------------"
	echo "$1"
	echo "------------------------------------------------------------"
}

ok() { echo "OK:   $*"; }
warn() { echo "WARN: $*"; }
fail() {
	echo "FAIL: $*"
	exit 1
}

# ------------------------------------------------------------
# Banner
# ------------------------------------------------------------
echo "============================================================"
echo " DNS TEST SUITE"
echo "============================================================"
echo "ENV_FILE   = ${ENV_FILE}"
echo "DNS_IP     = ${DNS_IP}"
echo "DOMAIN     = ${DOMAIN}"
echo "SUBDOMAIN  = ${SUBDOMAIN}"
echo "EXPECT IP  = ${IP4_EXPECTED}"
echo "INFINITO   = ${INFINITO_CONTAINER}"
echo

# ------------------------------------------------------------
# Host -> CoreDNS direct
# ------------------------------------------------------------
section "Host -> CoreDNS (direct queries)"

if command -v dig >/dev/null 2>&1; then
	a1="$(dig @"${DNS_IP}" "${DOMAIN}" A +short | head -n1 || true)"
	a2="$(dig @"${DNS_IP}" "${SUBDOMAIN}" A +short | head -n1 || true)"

	if [ "${a1}" = "${IP4_EXPECTED}" ]; then
		ok "${DOMAIN} A -> ${a1}"
	else
		fail "${DOMAIN} A failed (got '${a1}')"
	fi

	if [ "${a2}" = "${IP4_EXPECTED}" ]; then
		ok "${SUBDOMAIN} A -> ${a2}"
	else
		fail "${SUBDOMAIN} A failed (got '${a2}')"
	fi
else
	warn "dig not found on host — skipping host direct DNS tests"
fi

# ------------------------------------------------------------
# Host -> CoreDNS AAAA sanity check (must NOT return SERVFAIL)
# ------------------------------------------------------------
section "Host -> CoreDNS (AAAA sanity check)"

if command -v dig >/dev/null 2>&1; then
	aaaa1="$(dig @"${DNS_IP}" "${DOMAIN}" AAAA +comments +noall +answer || true)"
	aaaa2="$(dig @"${DNS_IP}" "${SUBDOMAIN}" AAAA +comments +noall +answer || true)"

	echo "AAAA ${DOMAIN}:"
	echo "${aaaa1:-<empty>}"
	echo

	echo "AAAA ${SUBDOMAIN}:"
	echo "${aaaa2:-<empty>}"
	echo

	# dig exits 0 even on NXDOMAIN, so we check for SERVFAIL explicitly
	status1="$(dig @"${DNS_IP}" "${DOMAIN}" AAAA +comments 2>&1 | grep -i status || true)"
	status2="$(dig @"${DNS_IP}" "${SUBDOMAIN}" AAAA +comments 2>&1 | grep -i status || true)"

	echo "${status1}"
	echo "${status2}"

	echo "${status1}" | grep -qi "SERVFAIL" && fail "AAAA lookup returned SERVFAIL for ${DOMAIN}"
	echo "${status2}" | grep -qi "SERVFAIL" && fail "AAAA lookup returned SERVFAIL for ${SUBDOMAIN}"

	ok "AAAA sanity check passed (no SERVFAIL)"
else
	warn "dig not found on host — skipping AAAA sanity test"
fi

# ------------------------------------------------------------
# CoreDNS container
# ------------------------------------------------------------
section "CoreDNS container status"

_coredns_name="${INFINITO_RUNNER_PREFIX:-infinito}-coredns"
if docker ps --filter name="${_coredns_name}" --format '{{.Names}}' | grep -q "${_coredns_name}"; then
	docker ps --filter name="${_coredns_name}" --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
	docker logs --tail=10 "${_coredns_name}" || true
	ok "CoreDNS container is running"
else
	fail "CoreDNS container not running"
fi

# ------------------------------------------------------------
# Infinito outer container DNS
# ------------------------------------------------------------
section "Infinito container (outer) DNS"

docker exec "${INFINITO_CONTAINER}" sh -lc "
  set -e

  echo '>>> /etc/resolv.conf'
  cat /etc/resolv.conf || true
  echo

  echo '>>> getent hosts'
  h1=\$(getent hosts ${DOMAIN} | awk '{print \$1}' || true)
  h2=\$(getent hosts ${SUBDOMAIN} | awk '{print \$1}' || true)

  echo \"${DOMAIN} -> \${h1}\"
  echo \"${SUBDOMAIN} -> \${h2}\"

  [ \"\${h1}\" = \"${IP4_EXPECTED}\" ] || exit 11
  [ \"\${h2}\" = \"${IP4_EXPECTED}\" ] || exit 12
"

ok "Outer container DNS works"

# ------------------------------------------------------------
# DONE
# ------------------------------------------------------------
section "DONE"
echo "DNS chain is fully functional:"
echo "Host -> CoreDNS -> Outer container -> Inner container"
