from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.builder import BuildContext, EnvBuilder
from utils.env.handlers.infinito import infra as handler
from utils.env.handlers.infinito.cache.paths import base

_BLANK = {
    handler.RUNNER_IP_KEY: "",
    handler.CACHE_DIR_KEY: "",
    handler.RUNNER_CONTAINER_KEY: "",
    **dict.fromkeys(handler.CACHE_IP_KEYS, ""),
}


def _apply(subnet: str) -> dict[str, str]:
    eb = EnvBuilder()
    eb.setdefault("INFINITO_INFRA_SUBNET", subnet)
    handler.apply(
        eb,
        BuildContext(
            static={},
            static_comments={},
            repo_root=Path("/repo"),
            on_gha=False,
            on_act=False,
        ),
    )
    return eb.values


class TestInfraHandler(unittest.TestCase):
    @patch.dict(os.environ, {**_BLANK, "INFINITO_INFRA_SUBNET": ""}, clear=False)
    def test_the_runner_address_follows_the_subnet(self) -> None:
        self.assertEqual(_apply("10.47.0.0/24")[handler.RUNNER_IP_KEY], "10.47.0.2")
        self.assertEqual(_apply("10.48.0.0/24")[handler.RUNNER_IP_KEY], "10.48.0.2")

    @patch.dict(os.environ, {**_BLANK, "INFINITO_INFRA_SUBNET": ""}, clear=False)
    def test_the_runner_binds_the_cache_base(self) -> None:
        self.assertEqual(_apply("10.47.0.0/24")[handler.CACHE_DIR_KEY], str(base()))

    @patch.dict(os.environ, {**_BLANK, "INFINITO_INFRA_SUBNET": ""}, clear=False)
    def test_the_three_cache_addresses_equal_the_runner(self) -> None:
        values = _apply("10.47.0.0/24")
        self.assertEqual({values[key] for key in handler.CACHE_IP_KEYS}, {"10.47.0.2"})

    @patch.dict(
        os.environ,
        {
            **_BLANK,
            "INFINITO_INFRA_SUBNET": "",
            "INFINITO_INFRA_RUNNER_IP": "172.30.0.2",
            "INFINITO_CACHE_REGISTRY_IP": "172.30.0.6",
            "INFINITO_CACHE_PACKAGE_IP": "172.30.0.5",
            "INFINITO_CACHE_PACKAGE_FRONTEND_IP": "172.30.0.4",
        },
        clear=False,
    )
    def test_a_stale_exported_cache_address_is_replaced(self) -> None:
        values = _apply("10.47.0.0/24")
        keys = (handler.RUNNER_IP_KEY, *handler.CACHE_IP_KEYS)
        self.assertEqual({values[key] for key in keys}, {"10.47.0.2"})

    @patch.dict(os.environ, {**_BLANK, "INFINITO_INFRA_SUBNET": ""}, clear=False)
    def test_default_env_carries_no_per_checkout_cache_address(self) -> None:
        from utils.cache.files import PROJECT_ROOT, read_text

        text = read_text(str(PROJECT_ROOT / "default.env"))
        for key in handler.CACHE_IP_KEYS:
            self.assertNotIn(f"\n{key}=", text, key)

    @patch.dict(os.environ, {**_BLANK, "INFINITO_INFRA_SUBNET": ""}, clear=False)
    def test_one_key_names_the_runner_container(self) -> None:
        self.assertEqual(
            _apply("10.47.0.0/24")[handler.RUNNER_CONTAINER_KEY],
            "infinito-infra-runner",
        )

    @patch.dict(
        os.environ,
        {**_BLANK, "INFINITO_INFRA_SUBNET": "", handler.RUNNER_CONTAINER_KEY: "other"},
        clear=False,
    )
    def test_an_exported_runner_name_wins(self) -> None:
        self.assertEqual(_apply("10.47.0.0/24")[handler.RUNNER_CONTAINER_KEY], "other")

    @patch.dict(os.environ, {**_BLANK, "INFINITO_INFRA_SUBNET": ""}, clear=False)
    def test_a_wider_subnet_fails_the_dotenv(self) -> None:
        with self.assertRaises(ValueError):
            _apply("10.47.0.0/16")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
