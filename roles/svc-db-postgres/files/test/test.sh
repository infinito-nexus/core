#!/usr/bin/env bash
# shellcheck shell=bash
#
# svc-db-postgres credential test. Authenticate to the database with real
# credentials and run a trivial query (SELECT 1). The transport depends on the
# variant:
#   tor enabled  (variant 0, exposed) -> over the Tor network: connect to
#                <node-onion>:<port> through the SOCKS proxy (psycopg2 via a
#                local SOCKS5 forward) and authenticate.
#   tor disabled (variant 1)          -> local: authenticate inside the DB
#                container over TCP (forces password auth via pg_hba).
#
# Env (rendered into test.env from templates/test.env.j2):
#   TOR_ENABLED     true|false        (services.tor.enabled, variant-aware)
#   TOR_SOCKS       SOCKS proxy       (set in test.env.j2)
#   ONION_HOST      node onion host   (svc-net-tor services.tor.node)
#   DB_PORT         onion-forwarded database port
#   DB_CONTAINER    database container name
#   DB_USER         database user     (postgres)
#   DB_NAME         database name     (postgres)
#   DB_PASSWORD_B64 base64 password   (avoids shell-quoting issues)
#   RETRIES         attempts          (default 20)
#   SLEEP_SECONDS   wait between      (default 15)

set -uo pipefail

RETRIES="${RETRIES:-20}"
SLEEP_SECONDS="${SLEEP_SECONDS:-15}"

DB_PASSWORD="$(printf '%s' "${DB_PASSWORD_B64}" | base64 -d 2>/dev/null)"
[ -n "${DB_PASSWORD}" ] || { echo "[FATAL] DB_PASSWORD_B64 missing or undecodable" >&2; exit 2; }

# Local: authenticate inside the container over TCP (127.0.0.1) so pg_hba
# enforces password auth — a genuine credential check, not a peer/trust socket.
auth_local() {
	container exec -e PGPASSWORD="${DB_PASSWORD}" "${DB_CONTAINER}" \
		psql -h 127.0.0.1 -U "${DB_USER}" -d "${DB_NAME}" -Atqc 'SELECT 1' 2>/dev/null |
		grep -qx 1
}

# Over Tor: psycopg2 (on this controller) connects through a local SOCKS5 -> onion
# forward and authenticates with the credentials.
auth_tor() {
	DB_USER="${DB_USER}" DB_NAME="${DB_NAME}" DB_PW="${DB_PASSWORD}" \
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
    s = socket.create_connection((ph, pp), timeout=120)
    s.settimeout(120)
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

import psycopg2

try:
    conn = psycopg2.connect(
        host="127.0.0.1", port=lport, user=os.environ["DB_USER"],
        password=os.environ["DB_PW"], dbname=os.environ["DB_NAME"],
        connect_timeout=120,
    )
    cur = conn.cursor()
    cur.execute("SELECT 1")
    row = cur.fetchone()
    cur.close()
    conn.close()
except Exception as exc:
    print("auth error: %s" % exc, file=sys.stderr)
    sys.exit(1)
sys.exit(0 if row and row[0] == 1 else 1)
PY
}

run_auth() {
	if [ "${TOR_ENABLED}" = "true" ]; then
		auth_tor
	else
		auth_local
	fi
}

if [ "${TOR_ENABLED}" = "true" ]; then
	[ -n "${ONION_HOST}" ] || { echo "[FATAL] ONION_HOST unset but tor enabled" >&2; exit 2; }
	mode="over Tor"
else
	[ -n "${DB_CONTAINER}" ] || { echo "[FATAL] DB_CONTAINER unset for local auth" >&2; exit 2; }
	mode="local"
fi

attempt=1
while [ "${attempt}" -le "${RETRIES}" ]; do
	if run_auth; then
		echo "[OK]   postgres credential auth ${mode} succeeded (SELECT 1)"
		exit 0
	fi
	attempt=$((attempt + 1))
	[ "${attempt}" -le "${RETRIES}" ] && sleep "${SLEEP_SECONDS}"
done

echo "[FAIL] postgres credential auth ${mode} failed after ${RETRIES} attempts" >&2
exit 1
