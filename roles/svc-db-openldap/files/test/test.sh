#!/usr/bin/env bash
# shellcheck shell=bash
#
# svc-db-openldap credential test. Bind to the directory with the administrator
# DN + password (a real credential check) over the transport chosen by the
# variant:
#   tor enabled  (variant 0, exposed) -> over the Tor network: bind to
#                <node-onion>:<port> through the SOCKS proxy (python-ldap via a
#                local SOCKS5 forward).
#   tor disabled (variant 1)          -> local: bind inside the LDAP container
#                (ldapwhoami over TCP).
#
# Env (rendered into test.env from templates/test.env.j2):
#   TOR_ENABLED     true|false        (services.tor.enabled, variant-aware)
#   TOR_SOCKS       SOCKS proxy       (set in test.env.j2)
#   ONION_HOST      node onion host   (svc-net-tor services.tor.node)
#   DB_PORT         onion-forwarded LDAP port
#   DB_CONTAINER    LDAP container name
#   BIND_DN_B64     base64 administrator bind DN
#   DB_PASSWORD_B64 base64 bind password
#   RETRIES         attempts          (default 20)
#   SLEEP_SECONDS   wait between      (default 15)

set -uo pipefail

RETRIES="${RETRIES:-20}"
SLEEP_SECONDS="${SLEEP_SECONDS:-15}"

BIND_DN="$(printf '%s' "${BIND_DN_B64}" | base64 -d 2>/dev/null)"
DB_PASSWORD="$(printf '%s' "${DB_PASSWORD_B64}" | base64 -d 2>/dev/null)"
[ -n "${BIND_DN}" ] || { echo "[FATAL] BIND_DN_B64 missing or undecodable" >&2; exit 2; }
[ -n "${DB_PASSWORD}" ] || { echo "[FATAL] DB_PASSWORD_B64 missing or undecodable" >&2; exit 2; }

# Local: bind inside the container over TCP — a genuine credential check.
auth_local() {
	# -y /dev/stdin keeps the bind password off the argv (fed via the pipe).
	printf '%s' "${DB_PASSWORD}" | container exec -i "${DB_CONTAINER}" \
		ldapwhoami -x -H ldap://127.0.0.1:389 -D "${BIND_DN}" -y /dev/stdin \
		>/dev/null 2>&1
}

# Over Tor: python-ldap (on this controller) binds through a local SOCKS5 -> onion
# forward with the administrator credentials.
auth_tor() {
	BIND_DN="${BIND_DN}" DB_PW="${DB_PASSWORD}" \
		python3 - "${TOR_SOCKS}" "${ONION_HOST}" "${DB_PORT}" <<'PY'
import os, socket, sys, threading

proxy, onion, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
ph, pp = proxy.rsplit(":", 1)
pp = int(pp)


def recvall(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise OSError("short read from SOCKS")
        buf += chunk
    return buf


def socks_connect():
    s = socket.create_connection((ph, pp), timeout=30)
    s.settimeout(30)
    s.sendall(b"\x05\x01\x00")
    if recvall(s, 2) != b"\x05\x00":
        raise OSError("SOCKS5 no-auth rejected")
    host = onion.encode()
    s.sendall(b"\x05\x01\x00\x03" + bytes([len(host)]) + host + port.to_bytes(2, "big"))
    hdr = recvall(s, 4)
    if hdr[1] != 0:
        raise OSError("SOCKS5 CONNECT failed rep=%d" % hdr[1])
    atyp = hdr[3]
    if atyp == 1:
        recvall(s, 4)
    elif atyp == 3:
        recvall(s, recvall(s, 1)[0])
    elif atyp == 4:
        recvall(s, 16)
    recvall(s, 2)
    s.settimeout(None)
    return s


def pipe(a, b):
    try:
        while True:
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except OSError:
        pass
    finally:
        try:
            b.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle(conn):
    try:
        up = socks_connect()
    except OSError:
        conn.close()
        return
    threading.Thread(target=pipe, args=(conn, up), daemon=True).start()
    pipe(up, conn)


lsock = socket.socket()
lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
lsock.bind(("127.0.0.1", 0))
lsock.listen(4)
lport = lsock.getsockname()[1]


def serve():
    while True:
        try:
            conn, _ = lsock.accept()
        except OSError:
            return
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


threading.Thread(target=serve, daemon=True).start()

import ldap

try:
    conn = ldap.initialize("ldap://127.0.0.1:%d" % lport)
    conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 30)
    conn.set_option(ldap.OPT_TIMEOUT, 30)
    conn.simple_bind_s(os.environ["BIND_DN"], os.environ["DB_PW"])
    who = conn.whoami_s()
    conn.unbind_s()
except Exception as exc:
    print("bind error: %s" % exc, file=sys.stderr)
    sys.exit(1)
sys.exit(0 if who else 1)
PY
}

if [ "${TOR_ENABLED}" = "true" ]; then
	[ -n "${ONION_HOST}" ] || { echo "[FATAL] ONION_HOST unset but tor enabled" >&2; exit 2; }
	mode="over Tor"
	attempt_fn=auth_tor
else
	[ -n "${DB_CONTAINER}" ] || { echo "[FATAL] DB_CONTAINER unset for local auth" >&2; exit 2; }
	mode="local"
	attempt_fn=auth_local
fi

attempt=1
while [ "${attempt}" -le "${RETRIES}" ]; do
	if "${attempt_fn}"; then
		echo "[OK]   openldap credential bind ${mode} succeeded"
		exit 0
	fi
	attempt=$((attempt + 1))
	[ "${attempt}" -le "${RETRIES}" ] && sleep "${SLEEP_SECONDS}"
done

echo "[FAIL] openldap credential bind ${mode} failed after ${RETRIES} attempts" >&2
exit 1
