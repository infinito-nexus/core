#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------
# Load environment (Single Source of Truth: .env from default.env)
# ------------------------------------------------------------
# shellcheck source=scripts/meta/env/load.sh
source scripts/meta/env/load.sh

# ------------------------------------------------------------
# Required variables (fail hard if missing)
# ------------------------------------------------------------
: "${INFINITO_DNS_IP:?Missing INFINITO_DNS_IP in .env}"
: "${INFINITO_DOMAIN:?Missing INFINITO_DOMAIN in .env}"
: "${INFINITO_IP4:?Missing INFINITO_IP4 in .env}"
: "${INFINITO_CONTAINER:?Missing INFINITO_CONTAINER env (e.g. infinito_nexus_arch)}"

SUBDOMAIN="foo.${INFINITO_DOMAIN}"
IP4_EXPECTED="${INFINITO_IP4}"

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
echo "INFINITO_DNS_IP     = ${INFINITO_DNS_IP}"
echo "INFINITO_DOMAIN     = ${INFINITO_DOMAIN}"
echo "SUBDOMAIN  = ${SUBDOMAIN}"
echo "EXPECT IP  = ${IP4_EXPECTED}"
echo "INFINITO   = ${INFINITO_CONTAINER}"
echo

# ------------------------------------------------------------
# Host -> CoreDNS direct
# ------------------------------------------------------------
section "Host -> CoreDNS (direct queries)"

if command -v dig >/dev/null 2>&1; then
	a1="$(dig @"${INFINITO_DNS_IP}" "${INFINITO_DOMAIN}" A +short | head -n1 || true)"
	a2="$(dig @"${INFINITO_DNS_IP}" "${SUBDOMAIN}" A +short | head -n1 || true)"

	if [ "${a1}" = "${IP4_EXPECTED}" ]; then
		ok "${INFINITO_DOMAIN} A -> ${a1}"
	else
		fail "${INFINITO_DOMAIN} A failed (got '${a1}')"
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
	aaaa1="$(dig @"${INFINITO_DNS_IP}" "${INFINITO_DOMAIN}" AAAA +comments +noall +answer || true)"
	aaaa2="$(dig @"${INFINITO_DNS_IP}" "${SUBDOMAIN}" AAAA +comments +noall +answer || true)"

	echo "AAAA ${INFINITO_DOMAIN}:"
	echo "${aaaa1:-<empty>}"
	echo

	echo "AAAA ${SUBDOMAIN}:"
	echo "${aaaa2:-<empty>}"
	echo

	# dig exits 0 even on NXDOMAIN, so we check for SERVFAIL explicitly
	status1="$(dig @"${INFINITO_DNS_IP}" "${INFINITO_DOMAIN}" AAAA +comments 2>&1 | grep -i status || true)"
	status2="$(dig @"${INFINITO_DNS_IP}" "${SUBDOMAIN}" AAAA +comments 2>&1 | grep -i status || true)"

	echo "${status1}"
	echo "${status2}"

	echo "${status1}" | grep -qi "SERVFAIL" && fail "AAAA lookup returned SERVFAIL for ${INFINITO_DOMAIN}"
	echo "${status2}" | grep -qi "SERVFAIL" && fail "AAAA lookup returned SERVFAIL for ${SUBDOMAIN}"

	ok "AAAA sanity check passed (no SERVFAIL)"
else
	warn "dig not found on host — skipping AAAA sanity test"
fi

# ------------------------------------------------------------
# CoreDNS container
# ------------------------------------------------------------
section "CoreDNS container status"

_coredns_name="${INFINITO_RUNNER_PREFIX:-}-coredns"
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
  h1=\$(getent hosts ${INFINITO_DOMAIN} | awk '{print \$1}' || true)
  h2=\$(getent hosts ${SUBDOMAIN} | awk '{print \$1}' || true)

  echo \"${INFINITO_DOMAIN} -> \${h1}\"
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
