from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import EnvBuilder, build_env
from utils.env.handlers.infinito import ip_range as handler


class TestUpperHalf(unittest.TestCase):
    def test_primary_subnet(self) -> None:
        self.assertEqual(handler.upper_half("172.30.0.0/24"), "172.30.0.128/25")

    def test_worktree_subnet(self) -> None:
        self.assertEqual(handler.upper_half("172.30.52.0/24"), "172.30.52.128/25")

    def test_a_host_address_is_not_a_subnet(self) -> None:
        with self.assertRaises(ValueError):
            handler.upper_half("172.30.0.10/24")


class TestFinalize(unittest.TestCase):
    def test_follows_the_subnet_in_the_builder(self) -> None:
        eb = EnvBuilder()
        eb.set(handler.SUBNET_KEY, "172.30.7.0/24")
        handler.finalize(eb)
        self.assertEqual(eb.values[handler.KEY], "172.30.7.128/25")

    def test_no_subnet_sets_no_pool(self) -> None:
        eb = EnvBuilder()
        with patch.dict(os.environ, {handler.SUBNET_KEY: ""}):
            handler.finalize(eb)
        self.assertNotIn(handler.KEY, eb.values)

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
        self.assertEqual(eb.values[handler.SUBNET_KEY], "172.30.9.0/24")
        self.assertEqual(eb.values[handler.KEY], "172.30.9.128/25")


if __name__ == "__main__":
    unittest.main()
