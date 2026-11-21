from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache.files import PROJECT_ROOT
from utils.inventory import tools
from utils.inventory.tools import GATEWAY_ROLE, RUNNER_IP_KEY, lane_url


class TestLaneUrl(unittest.TestCase):
    def _url(self, env: dict[str, str]) -> str:
        with patch.object(tools, "environment", return_value=env):
            return lane_url(Path(PROJECT_ROOT), GATEWAY_ROLE, "translate")

    def test_a_lane_service_answers_on_the_infra_runner_address(self) -> None:
        url = self._url({RUNNER_IP_KEY: "10.47.0.2", "INFINITO_BIND_IP": "127.0.0.9"})
        self.assertRegex(url, r"^http://10\.47\.0\.2:\d+$")

    def test_a_missing_runner_address_fails_loudly(self) -> None:
        with self.assertRaises(KeyError):
            self._url({"INFINITO_BIND_IP": "127.0.0.9"})

    def test_no_lane_address_file_or_ip_lookup_is_left(self) -> None:
        for name in ("ADDRESS", "lane_ip", "lane_address", "host_url"):
            self.assertFalse(hasattr(tools, name), name)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
