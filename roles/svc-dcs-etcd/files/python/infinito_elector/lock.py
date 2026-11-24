"""Lock backends: one named lease, held by at most one instance at a time."""

from __future__ import annotations

import abc
import base64
import json
import ssl
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

from . import LEASE_SECONDS

if TYPE_CHECKING:
    from collections.abc import Callable


class LockError(Exception):
    """The coordination store could not be reached or answered garbage.

    The elector treats it as "not renewed": it never assumes the lease is
    still held, so a lost store fails closed.
    """


class Lock(abc.ABC):
    """One lease identified by a key, held on behalf of one identity."""

    @abc.abstractmethod
    def acquire(self) -> bool:
        """Take the lease if nobody holds it. ``True`` when this identity now
        holds it."""

    @abc.abstractmethod
    def renew(self) -> bool:
        """Extend the lease. ``False`` when it is no longer held by this
        identity; :class:`LockError` when the store cannot tell."""

    @abc.abstractmethod
    def release(self) -> None:
        """Give the lease up so another instance can take it at once."""

    @abc.abstractmethod
    def holder(self) -> str | None:
        """The identity currently holding the lease, ``None`` when free."""


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _unb64(text: str) -> str:
    return base64.b64decode(text.encode()).decode()


def http_transport(
    endpoints: list[str], timeout: float = 2.0, ca_file: str | None = None
) -> Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]:
    """POST JSON to the etcd v3 gRPC gateway, trying each endpoint in turn.

    The endpoint that answered last is tried first, so a member on a lost
    node costs one timeout instead of one per call.

    Args:
        endpoints: base URLs such as ``http://etcd-a:2379``.
        timeout: per-request timeout in seconds; kept well under the renew
            deadline so one hung endpoint cannot eat it.
        ca_file: CA that signed the etcd server certificates; ``None`` keeps
            the system trust store. Explicit, because the deploy's CA trust
            override sets ``SSL_CERT_FILE`` to the project CA bundle.

    Returns:
        a callable ``(path, body, headers) -> decoded JSON`` raising
        :class:`LockError` once every endpoint failed.
    """

    context = ssl.create_default_context(cafile=ca_file) if ca_file else None
    order = list(endpoints)

    def answered(endpoint: str) -> None:
        order.remove(endpoint)
        order.insert(0, endpoint)

    def post(
        path: str, body: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        last: Exception | None = None
        for endpoint in list(order):
            if not endpoint.startswith(("http://", "https://")):
                raise LockError(f"etcd endpoint {endpoint!r} is not http(s)")
            request = urllib.request.Request(  # noqa: S310 - scheme checked as http(s) above
                endpoint.rstrip("/") + path,
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", **headers},
                method="POST",
            )
            try:
                with urllib.request.urlopen(  # noqa: S310 - scheme checked as http(s) above
                    request, timeout=timeout, context=context
                ) as response:
                    reply = json.loads(response.read().decode() or "{}")
            except urllib.error.HTTPError as error:
                if not 400 <= error.code < 500:
                    last = error
                    continue
                answered(endpoint)
                try:
                    reply = json.loads(error.read().decode() or "{}")
                except ValueError:
                    reply = {}
                return {"code": error.code, "error": error.reason, **reply}
            except (urllib.error.URLError, OSError, ValueError) as error:
                last = error
            else:
                answered(endpoint)
                return reply
        raise LockError(f"no etcd endpoint answered {path}: {last}")

    return post


class EtcdLeaseLock(Lock):
    """An etcd v3 lease bound to one key, spoken over the JSON gateway.

    Acquiring is a transaction that puts the key only while its create
    revision is 0, i.e. nobody holds it; the key carries the lease, so a
    holder that stops renewing loses the key when the lease expires.

    Args:
        transport: ``(path, body, headers) -> dict``; see
            :func:`http_transport`.
        key: the lock key, e.g. ``/infinito/mariadb/writer``.
        identity: this instance's host id, stored as the key's value.
        ttl: lease TTL in seconds.
        user: etcd user, or ``None`` when auth is off.
        password: that user's password.
    """

    def __init__(
        self,
        transport: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]],
        key: str,
        identity: str,
        *,
        ttl: int = LEASE_SECONDS,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        self._transport = transport
        self._key = key
        self._identity = identity
        self._ttl = ttl
        self._user = user
        self._password = password
        self._token: str | None = None
        self._lease: str | None = None

    def _call(
        self, path: str, body: dict[str, Any], retry: bool = True
    ) -> dict[str, Any]:
        headers = {}
        cached = self._token is not None
        if self._user:
            if self._token is None:
                self._token = self._transport(
                    "/v3/auth/authenticate",
                    {"name": self._user, "password": self._password or ""},
                    {},
                ).get("token")
                if not self._token:
                    raise LockError("etcd refused the elector's credentials")
            headers["Authorization"] = self._token
        try:
            reply = self._transport(path, body, headers)
        except LockError:
            if not (self._user and cached and retry):
                raise
            self._token = None
            return self._call(path, body, retry=False)
        if reply.get("error") or reply.get("code"):
            self._token = None
            if self._user and cached and retry:
                return self._call(path, body, retry=False)
            raise LockError(
                f"etcd {path}: {reply.get('error') or reply.get('message')}"
            )
        return reply

    def _value(self) -> tuple[str | None, str | None]:
        reply = self._call("/v3/kv/range", {"key": _b64(self._key)})
        kvs = reply.get("kvs") or []
        if not kvs:
            return None, None
        return _unb64(kvs[0].get("value", "")), str(kvs[0].get("lease", "")) or None

    def acquire(self) -> bool:
        lease = self._call("/v3/lease/grant", {"TTL": self._ttl}).get("ID")
        if not lease:
            raise LockError("etcd granted no lease")
        reply = self._call(
            "/v3/kv/txn",
            {
                "compare": [
                    {
                        "key": _b64(self._key),
                        "target": "CREATE",
                        "result": "EQUAL",
                        "create_revision": "0",
                    }
                ],
                "success": [
                    {
                        "request_put": {
                            "key": _b64(self._key),
                            "value": _b64(self._identity),
                            "lease": lease,
                        }
                    }
                ],
            },
        )
        if reply.get("succeeded"):
            self._lease = str(lease)
            return True
        self._call("/v3/lease/revoke", {"ID": lease})
        return False

    def renew(self) -> bool:
        if self._lease is None:
            return False
        reply = self._call("/v3/lease/keepalive", {"ID": self._lease})
        result = reply.get("result", reply)
        if int(result.get("TTL", 0) or 0) <= 0:
            self._lease = None
            return False
        holder, lease = self._value()
        if holder != self._identity or lease != self._lease:
            self._lease = None
            return False
        return True

    def release(self) -> None:
        lease, self._lease = self._lease, None
        if lease is not None:
            self._call("/v3/lease/revoke", {"ID": lease})

    def holder(self) -> str | None:
        return self._value()[0]
