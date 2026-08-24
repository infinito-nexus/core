from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from cli.administration.deploy.development.network import detect_outer_network_mtu


class TestDetectOuterNetworkMtu(unittest.TestCase):
    @patch.dict(os.environ, {"INFINITO_OUTER_NETWORK_MTU": "1300"}, clear=False)
    def test_prefers_explicit_outer_network_mtu_env(self) -> None:
        self.assertEqual(detect_outer_network_mtu(), "1300")

    @patch.dict(os.environ, {"INFINITO_OUTER_NETWORK_MTU": ""}, clear=True)
    @patch("cli.administration.deploy.development.network.Path.exists", autospec=True)
    @patch(
        "cli.administration.deploy.development.network.Path.read_text", autospec=True
    )
    def test_reads_outer_network_mtu_from_host_docker_daemon(
        self,
        read_text_mock: MagicMock,
        exists_mock: MagicMock,
    ) -> None:
        exists_mock.side_effect = lambda path: str(path) == "/etc/docker/daemon.json"
        read_text_mock.return_value = '{"mtu": 1400}'

        self.assertEqual(detect_outer_network_mtu(), "1400")

    @patch.dict(os.environ, {"INFINITO_OUTER_NETWORK_MTU": ""}, clear=True)
    @patch("cli.administration.deploy.development.network.Path.exists", autospec=True)
    @patch(
        "cli.administration.deploy.development.network.Path.read_text", autospec=True
    )
    def test_ignores_invalid_daemon_config(
        self,
        read_text_mock: MagicMock,
        exists_mock: MagicMock,
    ) -> None:
        exists_mock.side_effect = lambda path: str(path) == "/etc/docker/daemon.json"
        read_text_mock.return_value = '{"mtu": 64}'

        self.assertIsNone(detect_outer_network_mtu())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
