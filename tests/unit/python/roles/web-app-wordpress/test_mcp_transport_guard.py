"""The MCP transport guard covers the endpoint the specs probe.

``infinito-mcp-abilities.php`` refuses every REST route under one namespace
prefix that the site cannot attribute to a user. The specs probe one concrete
endpoint. If the adapter ever moves out of that namespace the guard stops
guarding anything, and both negative specs keep passing on a surface nobody
protects, so the two are read against each other here.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

_ROLE = PROJECT_ROOT / "roles/web-app-wordpress"
_PLUGIN = _ROLE / "files/mu-plugins/infinito-mcp-abilities.php"
_SPECS = (_ROLE / "files/playwright/test-mcp-guest.js",)

_GUARDED_PREFIX = re.compile(r"get_route\(\),\s*'/'\s*\),\s*'([\w-]+/)'")
_ENDPOINT = re.compile(r'MCP_ENDPOINT\s*=\s*"([^"]+)"')


class TestMcpTransportGuard(unittest.TestCase):
    def test_the_guarded_prefix_covers_every_endpoint_the_specs_probe(self) -> None:
        guarded = _GUARDED_PREFIX.search(read_text(str(_PLUGIN)))
        self.assertIsNotNone(
            guarded,
            "no route prefix found in infinito-mcp-abilities.php; the regex no "
            "longer matches how the transport guard scopes itself, so this "
            "test has stopped guarding anything",
        )
        prefix = guarded.group(1)

        for spec in _SPECS:
            with self.subTest(spec=spec.name):
                endpoint = _ENDPOINT.search(read_text(str(spec)))
                self.assertIsNotNone(endpoint, f"no MCP_ENDPOINT in {spec.name}")
                route = endpoint.group(1).removeprefix("/wp-json/")
                self.assertTrue(
                    route.startswith(prefix),
                    f"{spec.name} probes {endpoint.group(1)}, which does not sit "
                    f"under the guarded prefix '{prefix}'. The guard would let "
                    "an anonymous initialize through while the negative specs "
                    "still pass against whatever else answers",
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
