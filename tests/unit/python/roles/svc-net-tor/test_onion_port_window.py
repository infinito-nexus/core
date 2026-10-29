from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "svc-net-tor"
TEST_ENV = ROLE / "templates" / "test.env.j2"
TORRC = ROLE / "templates" / "torrc.j2"
TOR_DEFAULT_SOCKS_TIMEOUT = 120


class TestOnionPortWindow(unittest.TestCase):
    def test_an_attempt_outlasts_tors_socks_timeout(self) -> None:
        self.assertNotRegex(
            read_text(str(TORRC)),
            r"(?m)^SocksTimeout\b",
            "torrc now sets SocksTimeout; ONION_PORT_TIMEOUT has to be derived "
            "from it instead of from Tor's default",
        )
        declared = re.search(
            r"(?m)^ONION_PORT_TIMEOUT=(\d+)$", read_text(str(TEST_ENV))
        )
        self.assertIsNotNone(declared, "test.env.j2 declares no ONION_PORT_TIMEOUT")
        self.assertGreater(
            int(declared.group(1)),
            TOR_DEFAULT_SOCKS_TIMEOUT,
            "a port probe attempt that ends before Tor's SocksTimeout walks away "
            "from a rendezvous Tor is still building, and Tor never reaches its "
            "own verdict or logs it",
        )


if __name__ == "__main__":
    unittest.main()
