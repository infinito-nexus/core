from __future__ import annotations

import datetime as dt
import ipaddress
import json
import ssl
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CAS_MISMATCH = "check-and-set parameter did not match the current version"


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def make_ca(common_name: str) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(common_name))
        .issuer_name(_name(common_name))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    return key, cert


def make_leaf(
    ca_key: ec.EllipticCurvePrivateKey, ca_cert: x509.Certificate, host: str
) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(host))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(host))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def _pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


class OpenBaoStub:
    """
    Args:
        tokens: per OpenBao token, the ``<mount>/<path>`` prefixes it reads and
            writes; any other path answers 403.
        logins: per ``(role, jwt)`` of an accepted task token login, the token
            it yields.
    """

    def __init__(
        self, tokens: dict[str, list[str]], logins: dict[tuple[str, str], str]
    ) -> None:
        self.tokens = tokens
        self.logins = logins
        self.kv: dict[str, list[dict[str, Any]]] = {}
        self.requests: list[tuple[str, str, str]] = []
        self.login_count = 0
        self._dir = tempfile.TemporaryDirectory()
        scratch = Path(self._dir.name)
        ca_key, ca_cert = make_ca("openbao stub CA")
        leaf_key, leaf_cert = make_leaf(ca_key, ca_cert, "127.0.0.1")
        self.cafile = str(scratch / "ca.pem")
        Path(self.cafile).write_bytes(_pem(ca_cert))
        (scratch / "leaf.pem").write_bytes(_pem(leaf_cert))
        (scratch / "leaf.key").write_bytes(
            leaf_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(scratch / "leaf.pem"), str(scratch / "leaf.key"))
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return

            def _answer(self, status: int, body: dict[str, Any]) -> None:
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length) or b"{}")

            def do_GET(self) -> None:
                stub.handle(self, "GET", {})

            def do_POST(self) -> None:
                stub.handle(self, "POST", self._body())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.addr = f"https://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._dir.cleanup()

    def put(self, path: str, data: dict[str, Any]) -> None:
        self.kv.setdefault(path, []).append(dict(data))

    def _allowed(self, token: str, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self.tokens.get(token, []))

    def _list(self, handler: Any, token: str, path: str) -> None:
        mount, _, prefix = path.partition("/metadata/")
        folder = f"{mount}/{prefix}"
        if not self._allowed(token, folder):
            handler._answer(403, {"errors": ["permission denied"]})
            return
        keys = sorted(
            {
                rest.split("/", 1)[0] + ("/" if "/" in rest else "")
                for secret in self.kv
                if secret.startswith(folder) and (rest := secret[len(folder) :])
            }
        )
        if not keys:
            handler._answer(404, {"errors": []})
            return
        handler._answer(200, {"data": {"keys": keys}})

    def handle(self, handler: Any, method: str, body: dict[str, Any]) -> None:
        path = handler.path.split("?", 1)[0].removeprefix("/v1/")
        token = handler.headers.get("X-Vault-Token") or ""
        self.requests.append((method, path, token))
        if method == "POST" and path.startswith("auth/") and path.endswith("/login"):
            self.login_count += 1
            issued = self.logins.get((body.get("role"), body.get("jwt")))
            if issued is None:
                handler._answer(
                    400, {"errors": ["role could not be found or login refused"]}
                )
                return
            handler._answer(200, {"auth": {"client_token": issued}})
            return
        if method == "GET" and "/metadata/" in path:
            self._list(handler, token, path)
            return
        mount, _, rest = path.partition("/data/")
        secret = f"{mount}/{rest}"
        if not rest or not self._allowed(token, secret):
            handler._answer(403, {"errors": ["permission denied"]})
            return
        if method == "GET":
            versions = self.kv.get(secret)
            if not versions:
                handler._answer(404, {"errors": []})
                return
            handler._answer(
                200,
                {
                    "data": {
                        "data": versions[-1],
                        "metadata": {"version": len(versions)},
                    }
                },
            )
            return
        cas = (body.get("options") or {}).get("cas")
        if cas is not None and cas != len(self.kv.get(secret, [])):
            handler._answer(400, {"errors": [CAS_MISMATCH]})
            return
        self.put(secret, body.get("data") or {})
        handler._answer(200, {"data": {"version": len(self.kv[secret])}})
