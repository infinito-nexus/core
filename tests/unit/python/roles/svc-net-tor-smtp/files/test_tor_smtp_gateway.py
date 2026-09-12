"""What the Tor SMTP gateway accepts, and where it routes each recipient.

The gateway is not an open relay: it accepts a recipient ONLY when the domain
ends with ``.onion``, and it delivers each ``.onion`` domain's recipients in one
hop. The heavy dependencies (aiosmtpd, PySocks) are stubbed here so the routing
logic is testable without them, and ``_deliver`` is replaced so nothing dials
the network.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

from . import PROJECT_ROOT

MODULE = (
    PROJECT_ROOT
    / "roles"
    / "svc-net-tor-smtp"
    / "files"
    / "python"
    / "tor_smtp_gateway.py"
)

REQUIRED_ENV = {
    "TOR_SMTP_LISTEN_PORT": "1525",
    "TOR_SOCKS_HOST": "tor",
    "TOR_SOCKS_PORT": "9050",
    "TOR_SMTP_HELO": "node.example.onion",
}


def _load(env=None):
    """Import the daemon with the required env stubbed. A None override drops
    the key, so a test can assert a required var is missing."""
    socks_stub = types.ModuleType("socks")
    socks_stub.SOCKS5 = 2
    socks_stub.create_connection = lambda *a, **k: None
    controller_stub = types.ModuleType("aiosmtpd.controller")
    controller_stub.Controller = object
    aiosmtpd_pkg = types.ModuleType("aiosmtpd")
    aiosmtpd_pkg.controller = controller_stub
    merged = {k: v for k, v in {**REQUIRED_ENV, **(env or {})}.items() if v is not None}
    with (
        mock.patch.dict(
            sys.modules,
            {
                "socks": socks_stub,
                "aiosmtpd": aiosmtpd_pkg,
                "aiosmtpd.controller": controller_stub,
            },
        ),
        mock.patch.dict(os.environ, merged, clear=True),
    ):
        spec = importlib.util.spec_from_file_location("tor_smtp_gateway", MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class _Envelope:
    def __init__(self, mail_from="bot@x.onion", rcpt_tos=None, content=b"msg"):
        self.mail_from = mail_from
        self.rcpt_tos = list(rcpt_tos or [])
        self.content = content


class TestDomainGrouping(unittest.TestCase):
    def setUp(self):
        self.mod = _load()

    def test_recipients_group_by_domain(self):
        grouped = self.mod._group_by_domain(
            ["a@one.onion", "b@one.onion", "c@two.onion"]
        )
        self.assertEqual(
            grouped,
            {"one.onion": ["a@one.onion", "b@one.onion"], "two.onion": ["c@two.onion"]},
        )

    def test_domain_match_is_case_insensitive(self):
        grouped = self.mod._group_by_domain(["A@One.Onion"])
        self.assertEqual(list(grouped), ["one.onion"])


class TestRcptGate(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mod = _load()
        self.relay = self.mod.OnionRelay()

    async def _rcpt(self, address):
        env = _Envelope(rcpt_tos=[])
        reply = await self.relay.handle_RCPT(None, None, env, address, [])
        return reply, env

    async def test_an_onion_recipient_is_accepted(self):
        reply, env = await self._rcpt("biber@abc.onion")
        self.assertTrue(reply.startswith("250"))
        self.assertEqual(env.rcpt_tos, ["biber@abc.onion"])

    async def test_a_clearnet_recipient_is_refused(self):
        reply, env = await self._rcpt("biber@infinito.test")
        self.assertTrue(reply.startswith("550"))
        self.assertEqual(env.rcpt_tos, [])


class TestDataDelivery(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mod = _load()
        self.relay = self.mod.OnionRelay()

    async def test_each_onion_domain_gets_one_delivery(self):
        calls = []
        with mock.patch.object(
            self.mod, "_deliver", side_effect=lambda *a: calls.append(a)
        ):
            env = _Envelope(rcpt_tos=["a@one.onion", "b@one.onion", "c@two.onion"])
            reply = await self.relay.handle_DATA(None, None, env)
        self.assertTrue(reply.startswith("250"))
        self.assertEqual({c[0] for c in calls}, {"one.onion", "two.onion"})

    async def test_a_failed_hop_is_a_transient_error(self):
        def boom(*_a):
            raise OSError("tor down")

        with mock.patch.object(self.mod, "_deliver", side_effect=boom):
            env = _Envelope(rcpt_tos=["a@one.onion"])
            reply = await self.relay.handle_DATA(None, None, env)
        self.assertTrue(reply.startswith("451"))


class TestConfiguration(unittest.TestCase):
    def test_the_helo_name_comes_from_the_environment(self):
        mod = _load({"TOR_SMTP_HELO": "biber.node.onion"})
        self.assertEqual(mod.HELO_NAME, "biber.node.onion")

    def test_the_helo_never_falls_back_to_the_bind_address(self):
        """EHLO 0.0.0.0 is malformed; a missing HELO must fail loudly, not
        silently announce the bind address to the peer."""
        with self.assertRaises(KeyError):
            _load({"TOR_SMTP_HELO": None})

    def test_the_onion_hop_targets_the_well_known_smtp_port(self):
        self.assertEqual(_load().ONION_SMTP_PORT, 25)


if __name__ == "__main__":
    unittest.main()
