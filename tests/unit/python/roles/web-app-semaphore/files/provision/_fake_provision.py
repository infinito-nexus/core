from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import jinja2

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
FILES = ROLE / "files"
INTERFACE = json.loads(read_text(str(FILES / "opentofu" / "interface.json")))
CREDENTIALS = json.loads(read_text(str(FILES / "opentofu" / "credentials.json")))
WORKSPACE = "ws-4f1c2a3e-1b2c-4d5e-8f90-0123456789ab"
ZONE = "ws.example.org"
JWT = "header.claims.signature-of-the-task"
TOKEN = "bao-token-of-the-task"
STATE_KEYS = {"access_key": "STATEACCESSKEY0001", "secret_key": "state-secret-0001"}
ROUTE53_KEYS = {"access_key": "ROUTE53ACCESS0001", "secret_key": "route53-secret-01"}
TSIG = "dHNpZy1zZWNyZXQtb2YtdGhlLXdvcmtzcGFjZQ=="
PUBLIC_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
)
LOCK_ID = "0f6e5c3a-2b1d-4e8f-9a7b-6c5d4e3f2a1b"
SNAPSHOT_RECORD = f"platform/data/provision/transit/{WORKSPACE}"
GROUPS = {"web-app-proxmox": ["proxmox"], "svc-virt-incus": ["target"]}
CUSTOMER_TOKEN = "customer-hcloud-token-0001"
ZONE_TOKEN = "cloudflare-zones-token-0001"
ACCOUNT_ID = "0123456789abcdef0123456789abcdef"
CLOUDFLARE_ZONES = "/cloudflare/client/v4/zones"
FAKE_LOCKS = "/fake-locks/"
SCS_CREDENTIAL_ID = "4f0c1e2d3b4a"
SCS_CREDENTIAL_SECRET = "q7XwZ2pLk9Rt4VbNm3HsYd"
SCS_WRONG_SECRET = "Hn4rTz8QwE1yUo6KpJ"
KEYSTONE_SUBJECT = "gK5vQ1nJ8cTb6WfMr0Ae"
KEYSTONE_USER = "u9d8c7b6"
KEYSTONE_PROJECT = "p1a2b3c4"
KEYSTONE_TOKENS = "/v3/auth/tokens"
KEYSTONE_OWN_RECORD = (
    f"/v3/users/{KEYSTONE_USER}/application_credentials/{SCS_CREDENTIAL_ID}"
)
SECRET_PART = 6
STRICT = jinja2.Environment(
    undefined=jinja2.StrictUndefined,
    autoescape=jinja2.select_autoescape(default_for_string=False),
)
FAKE_TOFU = """#!{python}
import json, os, pathlib, stat, sys
cwd = pathlib.Path.cwd()
args = sys.argv[1:]
texts = {{
    str(path.relative_to(cwd)): path.read_text()
    for path in sorted(cwd.rglob("*"))
    if path.is_file() and path.suffix in (".json", ".hcl", ".tfbackend", ".crt", ".key")
}}
record = {{"argv": args, "cwd": str(cwd), "env": dict(os.environ), "texts": texts}}
for arg in args:
    if arg.startswith("-backend-config="):
        path = pathlib.Path(arg.split("=", 1)[1])
        path = path if path.is_absolute() else cwd / path
        record["backend"] = {{"text": path.read_text(), "mode": stat.S_IMODE(path.stat().st_mode)}}
with open(os.environ["FAKE_TOFU_LOG"], "a") as handle:
    handle.write(json.dumps(record) + "\\n")
plan = json.loads(pathlib.Path(os.environ["FAKE_TOFU_PLAN"]).read_text())
command = args[0] if args else ""
locks = os.environ.get("FAKE_TOFU_LOCKS")
if locks and command in ("apply", "destroy", "force-unlock"):
    import re, urllib.error, urllib.request
    backend = (cwd / "backend.tfbackend").read_text()
    bucket, key = (
        re.search("^" + name + ' = "([^"]*)"$', backend, re.M).group(1)
        for name in ("bucket", "key")
    )
    method = "DELETE" if command == "force-unlock" else "GET"
    try:
        urllib.request.urlopen(
            urllib.request.Request(locks + bucket + "/" + key + ".tflock", method=method)
        )
        held = method == "GET"
    except urllib.error.HTTPError:
        held = False
    if held:
        print("Error acquiring the state lock", file=sys.stderr)
        sys.exit(1)
if command == "state":
    print("\\n".join(plan.get("state", [])))
if command == "output":
    print(json.dumps(plan.get("outputs", {{}})))
if command == "show":
    print(json.dumps(plan.get("show", {{}})))
if command == "destroy" and command != plan.get("fail") and not plan.get("survivors"):
    plan["state"] = []
    pathlib.Path(os.environ["FAKE_TOFU_PLAN"]).write_text(json.dumps(plan))
sys.exit(1 if command == plan.get("fail") else 0)
"""
AUTHORIZATION = re.compile(
    r"AWS4-HMAC-SHA256 Credential=(?P<access>[^/]+)/"
    r"(?P<scope>[0-9]{8}/[a-z0-9-]+/s3/aws4_request), "
    r"SignedHeaders=(?P<signed>[a-z0-9;-]+), Signature=(?P<signature>[0-9a-f]{64})"
)
SIGNED_HEADERS = frozenset({"host", "x-amz-content-sha256", "x-amz-date"})
OUTPUTS = {
    "host": {"value": ["192.0.2.10"]},
    "host_key": {"value": PUBLIC_KEY},
    "server_id": {"value": "4711"},
    "fqdn": {"value": f"app.{WORKSPACE}.{ZONE}"},
}


def load(name):
    """Args:
        name: a dotted module of ``files/python``, e.g. ``provision.remote``.

    Returns:
        The module, the ``provision`` package importable as the runner
        imports it.
    """
    directory = str(FILES / "python")
    if directory not in sys.path:
        sys.path.insert(0, directory)
    path = FILES / "python" / f"{name.replace('.', '/')}.py"
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TempCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)


def default_secrets(dns_port):
    """Args:
        dns_port: the port of the fake knot primary.

    Returns:
        ``{KV path: data}`` of every secret a provision run may read.
    """
    tenant = f"tenant/data/{WORKSPACE}-provision"
    return {
        f"{tenant}/s3": dict(STATE_KEYS),
        f"{tenant}/dns": {
            "server": "127.0.0.1",
            "port": str(dns_port),
            "key_name": f"{WORKSPACE}.{ZONE}.",
            "key_algorithm": "hmac-sha512",
            "key_secret": TSIG,
            **ROUTE53_KEYS,
        },
        f"{tenant}/incus": {"certificate": "CLIENT-CERT", "key": "CLIENT-KEY"},
        f"{tenant}/providers/hetzner": {"token": CUSTOMER_TOKEN},
        f"{tenant}/proxmox": {"token_id": "ws@pve!provision", "secret": "secret-token"},
        f"{tenant}/scs": {
            "auth_url": "https://keystone.example.org/v3",
            "region_name": "RegionOne",
            "application_credential_id": "app-credential-id",
            "application_credential_secret": "app-credential-secret",
        },
        "platform/data/provision/incus-target": {
            "endpoint": "https://incus.example.org:8443",
            "certificate": "SERVER-CERT",
        },
        "platform/data/provision/proxmox-proxmox": {
            "endpoint": "https://proxmox.example.org:8006/"
        },
        "platform/data/provision/hetzner": {"token": "hcloud-platform-token"},
        "platform/data/provision/ionos": {"token": "ionos-platform-token"},
        f"platform/data/provision/cloudflare/{ZONE}": {
            "token": "cloudflare-zone-token"
        },
        "platform/data/provision/cloudflare-zones": {
            "token": ZONE_TOKEN,
            "account_id": ACCOUNT_ID,
        },
        SNAPSHOT_RECORD: {"key_created_at": "1763000000", "snapshot_at": "1763000005"},
    }


def signed_by_state_keys(method, path, headers, body_hash):
    """Args:
        method: the request method.
        path: the request target.
        headers: the request headers.
        body_hash: the SHA-256 of the body the server received.

    Returns:
        Whether the request carries an AWS SigV4 signature of the state keys
        over its signed headers and that body.
    """
    match = AUTHORIZATION.fullmatch(headers.get("authorization", ""))
    if match is None or match["access"] != STATE_KEYS["access_key"]:
        return False
    stamp = headers.get("x-amz-date", "")
    names = match["signed"].split(";")
    if (
        headers.get("x-amz-content-sha256") != body_hash
        or not set(names) >= SIGNED_HEADERS
        or not match["scope"].startswith(f"{stamp[:8]}/")
    ):
        return False
    canonical = "\n".join(
        [
            method,
            path,
            "",
            *(f"{name}:{headers.get(name, '').strip()}" for name in names),
            "",
            match["signed"],
            body_hash,
        ]
    )
    key = ("AWS4" + STATE_KEYS["secret_key"]).encode()
    for part in match["scope"].split("/"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    text = f"AWS4-HMAC-SHA256\n{stamp}\n{match['scope']}\n{digest}"
    expected = hmac.new(key, text.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, match["signature"])


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def _send(self, status, payload=b""):
        self.send_response(status)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _s3(self):
        platform = self.server
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if not signed_by_state_keys(
            self.command, self.path, self.headers, hashlib.sha256(body).hexdigest()
        ):
            self._send(403)
            return
        platform.s3_requests.append((self.command, self.path))
        if self.command == "DELETE":
            platform.objects.pop(self.path.lstrip("/"), None)
            self._send(204)
            return
        if self.command == "PUT":
            platform.objects[self.path.lstrip("/")] = body
            self._send(200)
            return
        body = platform.objects.get(self.path.lstrip("/"))
        self._send(404) if body is None else self._send(200, body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if (
            self.path == "/v1/auth/jwt/login"
            and body.get("jwt") == JWT
            and body.get("role") in (f"{WORKSPACE}-provision", f"{WORKSPACE}-zone")
        ):
            self.server.logins.append(body["role"])
            payload = {"auth": {"client_token": TOKEN}}
            self._send(200, json.dumps(payload).encode())
            return
        self._send(400)

    def _cloudflare(self):
        platform = self.server
        platform.cloudflare_requests.append(self.path)
        if self.headers.get("Authorization") != f"Bearer {ZONE_TOKEN}":
            self._send(403)
            return
        if platform.cloudflare_answer is not None:
            self._send(200, platform.cloudflare_answer)
            return
        target = urllib.parse.urlsplit(self.path.removeprefix(CLOUDFLARE_ZONES))
        if target.path in ("", "/"):
            query = urllib.parse.parse_qs(target.query)
            if query.get("account.id") != [ACCOUNT_ID]:
                self._send(400)
                return
            name = query["name"][0]
            result = [platform.zones[name]] if name in platform.zones else []
        else:
            zone_id = target.path.lstrip("/")
            held = [z for z in platform.zones.values() if z["id"] == zone_id]
            if not held:
                self._send(404)
                return
            result = held[0]
        self._send(200, json.dumps({"success": True, "result": result}).encode())

    def _lock(self):
        key = self.path.removeprefix(FAKE_LOCKS)
        if self.command == "DELETE":
            self.server.objects.pop(key, None)
            self._send(204)
            return
        self._send(200 if key in self.server.objects else 404)

    def do_GET(self):
        if self.path.startswith(FAKE_LOCKS):
            self._lock()
            return
        if self.path.startswith(CLOUDFLARE_ZONES):
            self._cloudflare()
            return
        if not self.path.startswith("/v1/"):
            self._s3()
            return
        path = self.path.removeprefix("/v1/")
        if self.headers.get("X-Vault-Token") != TOKEN:
            self._send(403)
            return
        self.server.reads.append(path)
        data = self.server.secrets.get(path)
        if data is None:
            self._send(404)
            return
        self._send(200, json.dumps({"data": {"data": data}}).encode())

    def do_HEAD(self):
        self._s3()

    def do_DELETE(self):
        if self.path.startswith(FAKE_LOCKS):
            self._lock()
            return
        self._s3()

    def do_PUT(self):
        self._s3()


class FakePlatform(ThreadingHTTPServer):
    """Args:
    secrets: ``{KV path: data}`` the fake OpenBao serves.
    objects: ``{bucket/key: bytes}`` the fake S3 endpoint serves.
    """

    def __init__(self, secrets, objects):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.secrets = secrets
        self.objects = objects
        self.zones = {}
        self.reads = []
        self.logins = []
        self.s3_requests = []
        self.cloudflare_requests = []
        self.cloudflare_answer = None
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server_address[1]}"

    def stop(self):
        self.shutdown()
        self.server_close()


def keystone_token():
    return {
        "user": {"id": KEYSTONE_USER},
        "project": {"id": KEYSTONE_PROJECT},
        "application_credential": {"id": SCS_CREDENTIAL_ID, "restricted": True},
    }


def keystone_record():
    return {
        "id": SCS_CREDENTIAL_ID,
        "project_id": KEYSTONE_PROJECT,
        "unrestricted": False,
        "expires_at": None,
    }


def secret_parts(text, *secrets):
    """Args:
        text: the output of a check.
        secrets: the values no output may carry.

    Returns:
        Every substring of :data:`SECRET_PART` characters of a secret the
        text holds.
    """
    return sorted(
        {
            secret[start : start + SECRET_PART]
            for secret in secrets
            for start in range(len(secret) - SECRET_PART + 1)
            if secret[start : start + SECRET_PART] in text
        }
    )


class _KeystoneHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def _send(self, status, document, headers):
        payload = json.dumps(document).encode()
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _own_token(self):
        return self.headers.get("X-Auth-Token") == KEYSTONE_SUBJECT

    def do_POST(self):
        self.server.requests.append(("POST", self.path))
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        presented = body["auth"]["identity"].get("application_credential")
        expected = {"id": SCS_CREDENTIAL_ID, "secret": SCS_CREDENTIAL_SECRET}
        if self.path != KEYSTONE_TOKENS or presented != expected:
            self._send(401, {"error": {"code": 401}}, {})
            return
        headers = {"X-Subject-Token": KEYSTONE_SUBJECT}
        self._send(201, {"token": self.server.token}, headers)

    def do_GET(self):
        self.server.requests.append(("GET", self.path))
        if self.path != KEYSTONE_OWN_RECORD or not self._own_token():
            self._send(404, {"error": {"code": 404}}, {})
            return
        self._send(200, {"application_credential": self.server.record}, {})

    def do_DELETE(self):
        self.server.requests.append(("DELETE", self.path))
        subject = self.headers.get("X-Subject-Token") == KEYSTONE_SUBJECT
        if self.path != KEYSTONE_TOKENS or not (subject and self._own_token()):
            self._send(404, {"error": {"code": 404}}, {})
            return
        self.server.revoked += 1
        self.send_response(204)
        self.end_headers()


class FakeKeystone(ThreadingHTTPServer):
    """Args:
    token: the ``token`` Keystone answers the credential with.
    record: the ``application_credential`` Keystone holds for it.
    """

    def __init__(self, token, record):
        super().__init__(("127.0.0.1", 0), _KeystoneHandler)
        self.token = token
        self.record = record
        self.requests = []
        self.revoked = 0
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def auth_url(self):
        return f"http://127.0.0.1:{self.server_address[1]}/v3"

    def stop(self):
        self.shutdown()
        self.server_close()


class FakeDNS:
    """Args:
    records: ``{(name, type): [rdata bytes]}`` the fake server answers.
    """

    def __init__(self, records):
        self.records = records
        self.questions = []
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", 0))
        self.port = self.socket.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                packet, peer = self.socket.recvfrom(4096)
            except OSError:
                return
            labels, offset = [], 12
            while packet[offset]:
                length = packet[offset]
                labels.append(packet[offset + 1 : offset + 1 + length].decode())
                offset += 1 + length
            kind = struct.unpack("!H", packet[offset + 1 : offset + 3])[0]
            name = ".".join(labels)
            self.questions.append((name, kind, packet[2] & 0x01))
            answers = self.records.get((name, kind), [])
            reply = packet[:2] + struct.pack("!HHHHH", 0x8400, 1, len(answers), 0, 0)
            reply += packet[12 : offset + 5]
            for data in answers:
                header = struct.pack("!HHIH", kind, 1, 300, len(data))
                reply += b"\xc0\x0c" + header + data
            self.socket.sendto(reply, peer)

    def stop(self):
        self.socket.close()


def _rendered(value):
    if isinstance(value, dict):
        return {key: _rendered(item) for key, item in value.items()}
    if isinstance(value, str):
        return STRICT.from_string(value).render(groups=GROUPS)
    return value


def services_catalog():
    services = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_SERVICES)))
    return _rendered(services["semaphore"]["workspaces"]["catalog"])


class Sandbox:
    """Args:
    flavor: the DNS flavor of the deployment.
    locks: whether the fake tofu refuses apply and destroy while the state's
        ``.tflock`` exists and deletes it on force-unlock, as OpenTofu does
        with ``use_lockfile``.
    """

    def __init__(self, flavor="knot", locks=False):
        self.locks = locks
        self.directory = Path(tempfile.mkdtemp(prefix="provision-test-"))
        self.core = self.directory / "core" / "roles" / "web-app-semaphore" / "files"
        for part in ("python", "opentofu", "shell"):
            shutil.copytree(FILES / part, self.core / part)
        self.checkout = self.directory / "checkout"
        (self.checkout / "provision").mkdir(parents=True)
        self.catalogs = self.directory / "catalogs"
        self.catalogs.mkdir()
        self.write_catalogs(services_catalog())
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(sys.executable)
        tofu = self.bin / "tofu"
        tofu.write_text(FAKE_TOFU.format(python=sys.executable), encoding="utf-8")
        tofu.chmod(0o755)
        self.tmp = self.directory / "tmp"
        self.tmp.mkdir()
        self.log = self.directory / "tofu.log"
        self.plan = self.directory / "plan.json"
        self.set_plan({"state": [], "outputs": OUTPUTS})
        self.dns = FakeDNS({})
        self.platform = FakePlatform(default_secrets(self.dns.port), {})
        self.flavor = flavor
        credentials = self.core / "opentofu" / "credentials.json"
        spec = json.loads(read_text(str(credentials)))
        spec["zone"]["api"] = f"{self.platform.origin}{CLOUDFLARE_ZONES}"
        credentials.write_text(json.dumps(spec), encoding="utf-8")

    def write_catalogs(self, catalogs):
        for provider, catalog in catalogs.items():
            (self.catalogs / f"{provider}.json").write_text(
                json.dumps(catalog), encoding="utf-8"
            )

    def set_plan(self, plan):
        self.plan.write_text(json.dumps(plan), encoding="utf-8")

    def tfvars(self, values=None, name="SO-2026-1"):
        document = {
            "name": name,
            "flavor": "cloud",
            "size": "demo",
            "region": "default",
            "ssh_public_key": PUBLIC_KEY,
            "dns_label": "app",
        }
        document.update(values or {})
        path = self.checkout / "provision" / f"{name}.tfvars.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def environment(self, **overrides):
        env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": str(self.directory),
            "TMPDIR": str(self.tmp),
            "SALES_ORDER": "SO-2026",
            "LINE": "1",
            "PROVIDER_TOKEN": "platform",
            "WORKSPACE": WORKSPACE,
            "WORKSPACE_DNS_ZONE": ZONE,
            "WORKSPACE_DNS_ZONE_ID": "" if self.flavor == "knot" else "Z0123456789",
            "WORKSPACE_TARGETS": "192.0.2.10:22,[2001:db8::10]:2222",
            "SEMAPHORE_JWT": JWT,
            "SEMAPHORE_TASK_ID": "987654",
            "BAO_ADDR": self.platform.origin,
            "PROVISION_STATE_ENDPOINT": self.platform.origin,
            "PROVISION_CATALOG_DIR": str(self.catalogs),
            "PROVISION_DNS_FLAVOR": self.flavor,
            "FAKE_TOFU_LOG": str(self.log),
            "FAKE_TOFU_PLAN": str(self.plan),
            "FAKE_TOFU_LOCKS": (
                f"{self.platform.origin}{FAKE_LOCKS}" if self.locks else None
            ),
        }
        env.update(overrides)
        return {name: value for name, value in env.items() if value is not None}

    def run(self, script, *arguments, **overrides):
        """Args:
            script: ``provision``, ``destroy``, ``unlock``, ``dns`` or ``zone``.
            arguments: extra arguments, which every script refuses.
            overrides: environment values to set, None to drop one.

        Returns:
            The finished process; :meth:`calls` then holds its calls only.
        """
        self.log.unlink(missing_ok=True)
        return subprocess.run(
            [
                "bash",
                str(self.core / "shell" / "repository" / f"{script}.sh"),
                *arguments,
            ],
            cwd=self.checkout,
            env=self.environment(**overrides),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def calls(self):
        if not self.log.is_file():
            return []
        lines = self.log.read_text().splitlines()  # nocheck: cache-read  stub call log
        return [json.loads(line) for line in lines]

    def commands(self):
        return [call["argv"][0] for call in self.calls()]

    def close(self):
        self.platform.stop()
        self.dns.stop()
        shutil.rmtree(self.directory, ignore_errors=True)
