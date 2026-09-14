from __future__ import annotations

import importlib.util
import unittest
import urllib.error
from typing import ClassVar

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/svc-ai-litellm/files/python/probe_auth.py"


def load_script() -> object:
    spec = importlib.util.spec_from_file_location("probe_auth", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_script()

CONSUMER_KEY = "sk-consumer"
MINTED_KEY = "sk-minted"


class FakeGateway:
    """A gateway answering from a declared key state.

    Args:
        accepted: keys the gateway answers 200 for.
        anonymous_status: status an unauthenticated caller receives.
        revocation_lag: how many status reads a deleted key keeps answering 200.
    """

    def __init__(
        self,
        accepted: set[str],
        anonymous_status: int = 401,
        revocation_lag: int = 0,
    ) -> None:
        self.accepted = set(accepted)
        self.anonymous_status = anonymous_status
        self.revocation_lag = revocation_lag
        self.aliases: dict[str, str] = {}
        self.stale_reads: dict[str, int] = {}
        self.slept: list[int] = []

    def _revoke(self, key: str) -> None:
        self.accepted.discard(key)
        self.stale_reads[key] = self.revocation_lag

    def status(self, key: str | None) -> int:
        if key is None:
            return self.anonymous_status
        if key in self.accepted:
            return 200
        if self.stale_reads.get(key, 0) > 0:
            self.stale_reads[key] -= 1
            return 200
        return 401

    def call(self, method: str, path: str, body: dict | None = None):
        if path == "/key/delete":
            for key in body.get("keys", []):
                self._revoke(key)
            for alias in body.get("key_aliases", []):
                if alias not in self.aliases:
                    raise urllib.error.HTTPError("/", 404, "", None, None)
                self._revoke(self.aliases.pop(alias))
            return {}
        self.aliases[body["key_alias"]] = MINTED_KEY
        self.accepted.add(MINTED_KEY)
        return {"key": MINTED_KEY}

    def sleep(self, seconds: int) -> None:
        self.slept.append(seconds)


def run(gateway: FakeGateway) -> None:
    MODULE.probe(gateway.status, gateway.call, CONSUMER_KEY, gateway.sleep)


class TestProbeAuth(unittest.TestCase):
    ACCEPTED: ClassVar[set[str]] = {CONSUMER_KEY}

    def test_a_closed_and_isolated_gateway_passes(self) -> None:
        run(FakeGateway(self.ACCEPTED))

    def test_an_open_gateway_is_rejected(self) -> None:
        with self.assertRaises(MODULE.ProbeError) as caught:
            run(FakeGateway(self.ACCEPTED, anonymous_status=200))
        self.assertIn("without a key", str(caught.exception))

    def test_a_gateway_honouring_a_forged_token_is_rejected(self) -> None:
        forged = "sk-" + "0" * 32
        with self.assertRaises(MODULE.ProbeError) as caught:
            run(FakeGateway({CONSUMER_KEY, forged}))
        self.assertIn("forged bearer token", str(caught.exception))

    def test_a_revocation_that_never_takes_effect_is_rejected(self) -> None:
        gateway = FakeGateway(self.ACCEPTED, revocation_lag=99)
        with self.assertRaises(MODULE.ProbeError) as caught:
            run(gateway)
        self.assertIn("revocation does not take effect", str(caught.exception))
        self.assertEqual(MODULE.REVOCATION_ATTEMPTS, len(gateway.slept))

    def test_a_lagging_revocation_is_awaited_rather_than_failed(self) -> None:
        gateway = FakeGateway(self.ACCEPTED, revocation_lag=2)
        run(gateway)
        self.assertEqual([MODULE.REVOCATION_DELAY] * 2, gateway.slept)

    def test_a_revocation_that_takes_a_consumer_down_is_rejected(self) -> None:
        class Collateral(FakeGateway):
            def call(self, method: str, path: str, body: dict | None = None):
                result = super().call(method, path, body)
                if path == "/key/delete" and body.get("keys"):
                    self.accepted.discard(CONSUMER_KEY)
                return result

        with self.assertRaises(MODULE.ProbeError) as caught:
            run(Collateral(self.ACCEPTED))
        self.assertIn("not isolated", str(caught.exception))

    def test_a_stale_probe_alias_is_cleared_before_minting(self) -> None:
        gateway = FakeGateway(self.ACCEPTED)
        gateway.aliases[MODULE.PROBE_ALIAS] = "sk-stale"
        gateway.accepted.add("sk-stale")
        run(gateway)
        self.assertNotIn("sk-stale", gateway.accepted)


if __name__ == "__main__":
    unittest.main()
