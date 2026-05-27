#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------
# Optional env overrides (with safe defaults)
# ------------------------------------------------------------
: "${BUSYBOX_IMAGE:?Missing Busybox image}"
: "${NODE_IMAGE:?Missing Busybox image}"

# ------------------------------------------------------------
# Required env (must already be present in the container)
# ------------------------------------------------------------
: "${DNS_IP:?Missing env DNS_IP}"
: "${DOMAIN:?Missing env DOMAIN}"
: "${IP4:?Missing env IP4}"

SUBDOMAIN="foo.${DOMAIN}"
IP4_EXPECTED="${IP4}"

section() {
  echo
  echo "------------------------------------------------------------"
  echo "$1"
  echo "------------------------------------------------------------"
}

ok()   { echo "OK:   $*"; }
fail() { echo "FAIL: $*"; exit 1; }

# ------------------------------------------------------------
# Wait for Docker-in-Docker daemon
# ------------------------------------------------------------
section "Wait for dockerd (DinD)"

for i in $(seq 1 60); do
  if [ -S /var/run/docker.sock ] && container info >/dev/null 2>&1; then
    ok "dockerd ready"
    break
  fi
  echo "waiting for dockerd... (${i}/60)" >&2
  sleep 1
done

[ -S /var/run/docker.sock ] || fail "docker.sock missing after waiting"
container info >/dev/null 2>&1 || fail "container info still failing after waiting"

# ------------------------------------------------------------
# DNS tests via Busybox (A + check "no SERVFAIL" robustly)
# ------------------------------------------------------------
section "Docker-in-Docker DNS (busybox: A + no SERVFAIL)"

container run --rm --dns "${DNS_IP}" "${BUSYBOX_IMAGE}" sh -lc "
  set -e

  test_lookup_a() {
    name=\"\$1\"
    out=\$(nslookup \"\$name\" 2>&1 || true)
    echo \"\$out\"
    echo \"\$out\" | grep -q \"Address: ${IP4_EXPECTED}\" || {
      echo \"A lookup failed for \$name (expected ${IP4_EXPECTED})\"
      exit 1
    }
  }

  # We don't require AAAA, but we must never see SERVFAIL (that broke Node/getaddrinfo).
  test_lookup_no_servfail() {
    name=\"\$1\"
    out=\$(nslookup \"\$name\" 2>&1 || true)
    echo \"\$out\"
    if echo \"\$out\" | grep -q \"SERVFAIL\"; then
      echo \"DNS lookup returned SERVFAIL for \$name\"
      exit 1
    fi
  }

  test_lookup_a \"${DOMAIN}\"
  test_lookup_a \"${SUBDOMAIN}\"

  test_lookup_no_servfail \"${DOMAIN}\"
  test_lookup_no_servfail \"${SUBDOMAIN}\"
"

ok "Inner container DNS works (A present; no SERVFAIL)"

# ------------------------------------------------------------
# Node / getaddrinfo test (this is what CSP checker uses)
# ------------------------------------------------------------
section "Docker-in-Docker DNS (node/getaddrinfo)"

container run --rm --dns "${DNS_IP}" "${NODE_IMAGE}" sh -lc "
  set -e
  node -e \"
    const dns = require('dns');
    dns.lookup('${DOMAIN}', { all: true }, (e, a) => {
      console.log('err', e && e.code, e && e.message);
      console.log('addrs', a);
      process.exit(e ? 1 : 0);
    });
  \"
"

ok "Node/getaddrinfo DNS works"

echo
echo "============================================================"
echo "DNS health check completed successfully."
echo "============================================================"
