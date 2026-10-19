"""Lint: no static IP of the compose stack lies in its dynamic IPAM pool.

Containers that join the bridge without an ``ipv4_address`` take the lowest
free address of ``INFINITO_IP_RANGE``. A static address inside that pool can be
taken by such a container first, and the stack that owns it then fails with
"Address already in use". The pool is the upper half of ``INFINITO_SUBNET``, so
every static address of the primary (``default.env``) and every worktree pin
(``scripts/system/worktree/up.sh``) must stay in the lower half.
"""

from __future__ import annotations

import ipaddress
import re
import unittest

from utils.cache.files import read_text
from utils.env.handlers.infinito.ip_range import upper_half
from utils.env.parser import parse_static_env

from . import PROJECT_ROOT

_WORKTREE_PIN_RE = re.compile(
    r"^(?P<key>INFINITO_[A-Z0-9_]+)=172\.30\.\$\{slot\}\.(?P<host>\d+)$",
    re.MULTILINE,
)


class TestStaticIpsOutsideIpRange(unittest.TestCase):
    def test_the_primary_statics_sit_below_the_pool(self) -> None:
        static = parse_static_env(PROJECT_ROOT / "default.env")
        subnet = ipaddress.ip_network(static["INFINITO_SUBNET"])
        pool = ipaddress.ip_network(upper_half(static["INFINITO_SUBNET"]))
        self.assertEqual(
            static["INFINITO_IP_RANGE"],
            str(pool),
            "default.env must declare INFINITO_IP_RANGE as the upper half of "
            "INFINITO_SUBNET, the value utils/env/handlers/infinito/ip_range.py derives.",
        )

        statics = {}
        for key, value in static.items():
            try:
                address = ipaddress.ip_address(value)
            except ValueError:
                continue
            if address in subnet:
                statics[key] = address
        self.assertIn("INFINITO_IP4", statics)
        offenders = sorted(key for key, address in statics.items() if address in pool)
        self.assertEqual(
            offenders,
            [],
            f"static IPs inside the dynamic pool {pool}: {offenders}",
        )

    def test_the_worktree_pins_sit_below_the_pool(self) -> None:
        pins = {
            match.group("key"): int(match.group("host"))
            for match in _WORKTREE_PIN_RE.finditer(
                read_text(str(PROJECT_ROOT / "scripts/system/worktree/up.sh"))
            )
        }
        self.assertIn("INFINITO_IP4", pins)
        offenders = sorted(key for key, host in pins.items() if host >= 128)
        self.assertEqual(
            offenders,
            [],
            f"worktree pins inside the dynamic pool 172.30.<slot>.128/25: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
