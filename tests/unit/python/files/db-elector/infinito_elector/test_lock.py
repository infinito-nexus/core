from __future__ import annotations

import base64
import io
import unittest
import urllib.error
from unittest import mock

from infinito_elector_src.lock import (
    EtcdLeaseLock,
    LockError,
    http_transport,
)

from . import _NAME  # noqa: F401  side-effect import registers infinito_elector_src


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


class FakeGateway:
    """A tiny etcd v3 JSON gateway: one key space, leases without expiry."""

    def __init__(self) -> None:
        self.kv: dict[str, tuple[str, str]] = {}
        self.leases: dict[str, int] = {}
        self.next_lease = 100
        self.down = False
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, path, body, headers):
        self.calls.append((path, body, headers))
        if self.down:
            raise LockError("down")
        if path == "/v3/auth/authenticate":
            return {"token": "tok"} if body["password"] == "pw" else {"error": "auth"}
        if path == "/v3/lease/grant":
            self.next_lease += 1
            self.leases[str(self.next_lease)] = body["TTL"]
            return {"ID": str(self.next_lease), "TTL": str(body["TTL"])}
        if path == "/v3/lease/keepalive":
            ttl = self.leases.get(body["ID"], 0)
            return {
                "result": {"ID": body["ID"], "TTL": str(ttl)}
                if ttl
                else {"ID": body["ID"]}
            }
        if path == "/v3/lease/revoke":
            self.leases.pop(body["ID"], None)
            self.kv = {k: v for k, v in self.kv.items() if v[1] != body["ID"]}
            return {}
        if path == "/v3/kv/range":
            if body["key"] not in self.kv:
                return {}
            value, lease = self.kv[body["key"]]
            return {"kvs": [{"key": body["key"], "value": value, "lease": lease}]}
        if path == "/v3/kv/txn":
            compare = body["compare"][0]
            assert compare["target"] == "CREATE" and compare["create_revision"] == "0"
            if compare["key"] in self.kv:
                return {"succeeded": False}
            put = body["success"][0]["request_put"]
            self.kv[put["key"]] = (put["value"], put["lease"])
            return {"succeeded": True}
        raise AssertionError(path)


def _lock(gateway, identity="m1", **kwargs) -> EtcdLeaseLock:
    return EtcdLeaseLock(gateway, "/infinito/mariadb/writer", identity, **kwargs)


class TestEtcdLeaseLock(unittest.TestCase):
    def test_acquire_is_exclusive(self) -> None:
        gateway = FakeGateway()
        first, second = _lock(gateway, "m1"), _lock(gateway, "m2")
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        self.assertEqual(second.holder(), "m1")
        self.assertEqual(gateway.leases.get("101"), 15)
        self.assertNotIn("102", gateway.leases)

    def test_renew_and_release(self) -> None:
        gateway = FakeGateway()
        lock = _lock(gateway)
        lock.acquire()
        self.assertTrue(lock.renew())
        lock.release()
        self.assertIsNone(lock.holder())
        self.assertFalse(lock.renew())

    def test_renew_fails_when_the_lease_expired(self) -> None:
        gateway = FakeGateway()
        lock = _lock(gateway)
        lock.acquire()
        gateway.leases.clear()
        self.assertFalse(lock.renew())

    def test_renew_fails_when_someone_else_holds_the_key(self) -> None:
        gateway = FakeGateway()
        lock = _lock(gateway)
        lock.acquire()
        gateway.kv[_b64("/infinito/mariadb/writer")] = (_b64("m2"), "999")
        self.assertFalse(lock.renew())

    def test_store_loss_raises(self) -> None:
        gateway = FakeGateway()
        lock = _lock(gateway)
        lock.acquire()
        gateway.down = True
        with self.assertRaises(LockError):
            lock.renew()

    def test_authenticates_and_sends_the_token(self) -> None:
        gateway = FakeGateway()
        _lock(gateway, user="elector", password="pw").acquire()
        self.assertEqual(gateway.calls[0][0], "/v3/auth/authenticate")
        self.assertEqual(gateway.calls[1][2], {"Authorization": "tok"})

    def test_bad_credentials_raise(self) -> None:
        with self.assertRaises(LockError):
            _lock(FakeGateway(), user="elector", password="nope").acquire()

    def test_a_token_from_a_rebuilt_store_is_replaced(self) -> None:
        gateway = FakeGateway()
        lock = _lock(gateway, user="elector", password="pw")
        lock.acquire()
        real = gateway.__call__
        stale = {"left": 1}

        def rebuilt(path, body, headers):
            if headers.get("Authorization") and stale["left"]:
                stale["left"] -= 1
                return {"code": 401, "error": "invalid auth token"}
            return real(path, body, headers)

        lock._transport = rebuilt
        self.assertTrue(lock.renew())
        self.assertEqual(
            [c[0] for c in gateway.calls].count("/v3/auth/authenticate"), 2
        )

    def test_a_token_a_rebuilt_store_hangs_on_is_replaced(self) -> None:
        gateway = FakeGateway()
        lock = _lock(gateway, user="elector", password="pw")
        lock.acquire()
        real = gateway.__call__
        stale = {"left": 1}

        def rebuilt(path, body, headers):
            if headers.get("Authorization") and stale["left"]:
                stale["left"] -= 1
                raise LockError(
                    "no etcd endpoint answered: The read operation timed out"
                )
            return real(path, body, headers)

        lock._transport = rebuilt
        self.assertEqual(lock.holder(), "m1")
        self.assertEqual(
            [c[0] for c in gateway.calls].count("/v3/auth/authenticate"), 2
        )

    def test_a_store_down_for_a_fresh_token_still_raises(self) -> None:
        gateway = FakeGateway()
        lock = _lock(gateway, user="elector", password="pw")
        lock.acquire()
        gateway.down = True
        with self.assertRaises(LockError):
            lock.holder()


class TestTransportErrors(unittest.TestCase):
    def test_a_client_error_reply_is_returned_not_skipped(self):
        error = urllib.error.HTTPError(
            "https://etcd:2379/v3/x",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"error":"invalid auth token","code":16}'),
        )
        with mock.patch("urllib.request.urlopen", side_effect=error):
            reply = http_transport(["https://etcd:2379"])("/v3/x", {}, {})
        self.assertEqual(reply["code"], 16)
        self.assertEqual(reply["error"], "invalid auth token")

    def test_a_server_error_tries_the_next_endpoint(self):
        error = urllib.error.HTTPError(
            "https://a:2379/v3/x", 503, "down", {}, io.BytesIO(b"")
        )
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":1}'
        endpoints = ["https://a:2379", "https://b:2379"]
        with mock.patch("urllib.request.urlopen", side_effect=[error, response]):
            reply = http_transport(endpoints)("/v3/x", {}, {})
        self.assertEqual(reply, {"ok": 1})

    def test_the_endpoint_that_answered_is_tried_first_next_time(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":1}'
        tried: list[str] = []

        def urlopen(request, **_):
            tried.append(request.full_url.split("/v3")[0])
            if request.full_url.startswith("https://dead"):
                raise urllib.error.URLError("timed out")
            return response

        post = http_transport(["https://dead:2379", "https://b:2379"])
        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            post("/v3/x", {}, {})
            post("/v3/y", {}, {})
        self.assertEqual(
            tried, ["https://dead:2379", "https://b:2379", "https://b:2379"]
        )


class TestTransportTrust(unittest.TestCase):
    def _post_with(self, ca_file):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        with (
            mock.patch("ssl.create_default_context") as create,
            mock.patch("urllib.request.urlopen", return_value=response) as urlopen,
        ):
            http_transport(["https://etcd:2379"], ca_file=ca_file)("/v3/x", {}, {})
        return create, urlopen.call_args.kwargs["context"]

    def test_the_etcd_ca_is_trusted_explicitly(self):
        create, context = self._post_with("/run/secrets/etcd-ca.crt")
        create.assert_called_once_with(cafile="/run/secrets/etcd-ca.crt")
        self.assertIs(context, create.return_value)

    def test_without_a_ca_the_system_store_is_used(self):
        create, context = self._post_with(None)
        create.assert_not_called()
        self.assertIsNone(context)


if __name__ == "__main__":
    unittest.main()
