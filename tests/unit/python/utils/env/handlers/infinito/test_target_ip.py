from __future__ import annotations

import ipaddress
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import build_env
from utils.env.context import EnvBuilder
from utils.env.handlers.infinito import target_ip as handler
from utils.env.handlers.infinito.ip_range import upper_half


class TestAddressIn(unittest.TestCase):
    def test_primary_subnet(self) -> None:
        self.assertEqual(handler.address_in("172.30.0.0/24"), "172.30.0.20")

    def test_worktree_subnet(self) -> None:
        self.assertEqual(handler.address_in("172.30.52.0/24"), "172.30.52.20")

    def test_stays_below_the_dynamic_pool(self) -> None:
        subnet = "172.30.0.0/24"
        pool = ipaddress.ip_network(upper_half(subnet))
        for offset in (handler.HOST_OFFSET, handler.RESOLVER_OFFSET):
            with self.subTest(offset=offset):
                self.assertNotIn(
                    ipaddress.ip_address(handler.host_in(subnet, offset)), pool
                )

    def test_a_subnet_too_small_for_the_host_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            handler.host_in("172.30.0.0/28", handler.RESOLVER_OFFSET)


class TestFinalize(unittest.TestCase):
    def test_follows_the_subnet_in_the_builder(self) -> None:
        eb = EnvBuilder()
        eb.set(handler.SUBNET_KEY, "172.30.7.0/24")
        handler.finalize(eb)
        self.assertEqual(eb.values[handler.KEY], "172.30.7.20")
        self.assertEqual(eb.values[handler.RESOLVER_KEY], "172.30.7.21")

    def test_no_subnet_sets_no_address(self) -> None:
        eb = EnvBuilder()
        with patch.dict(os.environ, {handler.SUBNET_KEY: ""}):
            handler.finalize(eb)
        self.assertNotIn(handler.KEY, eb.values)
        self.assertNotIn(handler.RESOLVER_KEY, eb.values)

    def test_build_env_derives_it_from_the_subnet_custom_env_pins(self) -> None:
        clean = {k: v for k, v in os.environ.items() if not k.startswith("INFINITO_")}
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            (repo_root / "custom.env").write_text(
                "INFINITO_SUBNET=172.30.9.0/24\n", encoding="utf-8"
            )
            with (
                patch.dict(os.environ, clean, clear=True),
                patch("utils.env.builder.detect_gha_act", return_value=(False, False)),
                patch(
                    "utils.env.handlers.infinito.inventory.run_helper",
                    return_value="",
                ),
            ):
                eb = build_env(
                    {"INFINITO_DISTRO": "debian", handler.SUBNET_KEY: "172.30.0.0/24"},
                    repo_root,
                )
        self.assertEqual(eb.values[handler.KEY], "172.30.9.20")
        self.assertEqual(eb.values[handler.RESOLVER_KEY], "172.30.9.21")


if __name__ == "__main__":
    unittest.main()
