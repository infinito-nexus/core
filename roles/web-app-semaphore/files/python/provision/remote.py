from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import hmac
import http.client
import ipaddress
import json
import signal
import ssl
import time
import urllib.parse

TIMEOUT = 30
SYSTEM_TRUST = ""


class RemoteError(Exception):
    """Args:
    message: the failed request, never a credential.
    """


def _loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def request(url, method, headers, body, cafile):
    """Args:
        url: an ``https`` URL, or ``http`` on a loopback address only.
        method: the HTTP method.
        headers: the request headers.
        body: the request body, None for none.
        cafile: a CA bundle that verifies the server, empty for the system trust.

    Returns:
        ``(status, body)`` of the answer.
    """
    status, _, payload = exchange(url, method, headers, body, cafile, TIMEOUT)
    return status, payload


def exchange(url, method, headers, body, cafile, timeout):
    """Args:
        url: an ``https`` URL, or ``http`` on a loopback address only.
        method: the HTTP method.
        headers: the request headers.
        body: the request body, None for none.
        cafile: a CA bundle that verifies the server, empty for the system trust.
        timeout: the seconds each socket operation may take.

    Returns:
        ``(status, headers, body)`` of the answer, the header names in lower
        case.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https":
        context = ssl.create_default_context(cafile=cafile or None)
        connection = http.client.HTTPSConnection(
            parts.hostname, parts.port, timeout=timeout, context=context
        )
    elif parts.scheme == "http" and _loopback(parts.hostname or ""):
        connection = http.client.HTTPConnection(
            parts.hostname, parts.port, timeout=timeout
        )
    else:
        raise RemoteError(f"{parts.scheme}://{parts.hostname} is no https origin")
    target = parts.path + (f"?{parts.query}" if parts.query else "")
    try:
        connection.request(method, target, body=body, headers=headers)
        answer = connection.getresponse()
        names = {name.lower(): value for name, value in answer.getheaders()}
        return answer.status, names, answer.read()
    except OSError as error:
        raise RemoteError(f"{method} {parts.hostname}{parts.path}: {error}") from None
    finally:
        connection.close()


class OpenBao:
    """Args:
    address: the OpenBao origin.
    cafile: a CA bundle that verifies it, empty for the system trust.
    """

    def __init__(self, address, cafile):
        self.address = address.rstrip("/")
        self.cafile = cafile
        self.token = ""

    def _call(self, method, path, body=None, missing_ok=False):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["X-Vault-Token"] = self.token
        data = None if body is None else json.dumps(body).encode("utf-8")
        if data is not None:
            headers["Content-Type"] = "application/json"
        status, payload = request(
            f"{self.address}/v1/{path}", method, headers, data, self.cafile
        )
        if status == 404 and missing_ok:
            return None
        if status not in (200, 204):
            raise RemoteError(f"OpenBao {method} {path}: HTTP {status}")
        return json.loads(payload or b"{}")

    def record(self, path):
        """Args:
            path: a KV v2 data path that may not exist yet.

        Returns:
            Its data, None when OpenBao holds nothing there.
        """
        answer = self._call("GET", path, missing_ok=True)
        if answer is None:
            return None
        return (answer.get("data") or {}).get("data") or None

    def login(self, role, jwt):
        """Args:
            role: the ``jwt`` role of the task.
            jwt: the task token Semaphore signed.

        Returns:
            The client token, kept for :meth:`read`.
        """
        answer = self._call("POST", "auth/jwt/login", {"role": role, "jwt": jwt})
        self.token = answer["auth"]["client_token"]
        return self.token

    def child(self, role, policy, ttl):
        """Args:
            role: the token role whose ``allowed_policies`` name ``policy``.
            policy: the one policy the child token carries, without ``default``.
            ttl: its lifetime, e.g. ``7200s``.

        Returns:
            A non-renewable child of the client token, which OpenBao revokes
            together with it.
        """
        answer = self._call(
            "POST",
            f"auth/token/create/{role}",
            {
                "policies": [policy],
                "ttl": ttl,
                "renewable": False,
                "no_default_policy": True,
            },
        )
        return answer["auth"]["client_token"]

    def revoke(self):
        """Returns:
        Once OpenBao revoked the client token and every child it created; a
        client without a token revokes nothing.
        """
        if self.token:
            self._call("POST", "auth/token/revoke-self", {})
            self.token = ""

    def read(self, path, fields):
        """Args:
            path: a KV v2 data path, e.g. ``tenant/data/ws-1-provision/s3``.
            fields: the fields the caller needs.

        Returns:
            ``{field: value}`` of those fields; a missing one raises.
        """
        data = (self._call("GET", path).get("data") or {}).get("data") or {}
        missing = sorted(set(fields) - set(data))
        if missing:
            raise RemoteError(f"OpenBao {path} lacks {', '.join(missing)}")
        return {field: str(data[field]) for field in fields}


class Cloudflare:
    """Args:
    zones: the zones endpoint of the Cloudflare API, ``https`` or loopback ``http``.
    token: the zone token, sent only in the ``Authorization`` header.
    """

    def __init__(self, zones, token):
        self.zones = zones.rstrip("/")
        self.token = token

    def _result(self, target, what, shape):
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        status, payload = request(
            f"{self.zones}{target}", "GET", headers, None, SYSTEM_TRUST
        )
        if status != 200:
            raise RemoteError(f"Cloudflare GET {what}: HTTP {status}")
        try:
            answer = json.loads(payload)
        except ValueError:
            answer = None
        if (
            not isinstance(answer, dict)
            or answer.get("success") is not True
            or not isinstance(answer.get("result"), shape)
        ):
            raise RemoteError(
                f"Cloudflare GET {what}: the answer is no successful "
                f"{shape.__name__} result"
            )
        return answer["result"]

    def held(self, name, account_id):
        """Args:
            name: the zone apex.
            account_id: the Cloudflare account the zone token acts in.

        Returns:
            Whether the account holds a zone of that name.
        """
        query = urllib.parse.urlencode({"name": name, "account.id": account_id})
        return bool(self._result(f"?{query}", f"zones of {name}", list))

    def zone(self, zone_id):
        """Args:
            zone_id: the id of a zone the account holds.

        Returns:
            ``status`` and ``name_servers`` the provider reports for it.
        """
        quoted = urllib.parse.quote(zone_id, safe="")
        result = self._result(f"/{quoted}", f"zone {zone_id}", dict)
        try:
            return {"status": result["status"], "name_servers": result["name_servers"]}
        except KeyError:
            raise RemoteError(
                f"Cloudflare GET zone {zone_id}: the answer holds no status and name_servers"
            ) from None


def _hmac(key, text):
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).digest()


class StateBucket:
    """Args:
    endpoint: the S3 origin of the state buckets.
    access_key: the access key of the workspace's S3 identity.
    secret_key: its secret key.
    region: the signing region.
    cafile: a CA bundle that verifies the endpoint, empty for the system trust.
    """

    def __init__(self, endpoint, access_key, secret_key, region, cafile):
        self.endpoint = endpoint.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.cafile = cafile

    def _headers(self, method, path, now, payload_hash):
        host = urllib.parse.urlsplit(self.endpoint).netloc
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": stamp,
        }
        signed = ";".join(sorted(headers))
        canonical = "\n".join(
            [
                method,
                path,
                "",
                *(f"{name}:{headers[name]}" for name in sorted(headers)),
                "",
                signed,
                payload_hash,
            ]
        )
        scope = f"{stamp[:8]}/{self.region}/s3/aws4_request"
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        key = ("AWS4" + self.secret_key).encode("utf-8")
        for part in (stamp[:8], self.region, "s3", "aws4_request"):
            key = _hmac(key, part)
        signature = hmac.new(
            key,
            f"AWS4-HMAC-SHA256\n{stamp}\n{scope}\n{digest}".encode(),
            hashlib.sha256,
        ).hexdigest()
        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key}/{scope}, "
            f"SignedHeaders={signed}, Signature={signature}"
        )
        return headers

    def _call(self, method, bucket, key, body=None):
        parts = urllib.parse.urlsplit(self.endpoint)
        path = urllib.parse.quote(f"{parts.path.rstrip('/')}/{bucket}/{key}", safe="/~")
        payload_hash = hashlib.sha256(body or b"").hexdigest()
        headers = self._headers(method, path, dt.datetime.now(dt.UTC), payload_hash)
        status, body = request(
            f"{parts.scheme}://{parts.netloc}{path}", method, headers, body, self.cafile
        )
        if status == 404:
            return None
        if status not in (200, 204):
            raise RemoteError(f"S3 {method} {bucket}/{key}: HTTP {status}")
        return body

    def get(self, bucket, key):
        """Args:
            bucket: the state bucket.
            key: the object key.

        Returns:
            The object's bytes, None when it does not exist.
        """
        return self._call("GET", bucket, key)

    def exists(self, bucket, key):
        """Args:
            bucket: the state bucket.
            key: the object key.

        Returns:
            Whether the object exists.
        """
        return self._call("HEAD", bucket, key) is not None

    def put(self, bucket, key, body):
        """Args:
        bucket: the state bucket.
        key: the object key.
        body: the object's bytes, signed by their SHA-256.
        """
        self._call("PUT", bucket, key, body)

    def delete(self, bucket, key):
        """Args:
        bucket: the state bucket.
        key: the object key; a missing object counts as deleted.
        """
        self._call("DELETE", bucket, key)


@contextlib.contextmanager
def alarm_deferred():
    """Returns:
        A context whose body no ``SIGALRM`` interrupts, the alarm keeping the
        deadline it had on entry.

    Raises:
        Whatever the ``SIGALRM`` handler raises, on exit, when that deadline
        passed during the body.
    """
    left, _ = signal.setitimer(signal.ITIMER_REAL, 0)
    deadline = time.monotonic() + left
    try:
        yield
    finally:
        if left:
            rest = deadline - time.monotonic()
            if rest > 0:
                signal.setitimer(signal.ITIMER_REAL, rest)
            else:
                signal.raise_signal(signal.SIGALRM)
