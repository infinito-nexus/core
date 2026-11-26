from __future__ import annotations

import unittest

from jinja2 import Environment, StrictUndefined, nodes, select_autoescape

from utils.cache.files import read_text

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "svc-net-tor"
TEST_ENV = ROLE / "templates" / "test.env.j2"
TORRC = ROLE / "templates" / "torrc.j2"
TOR_DEFAULT_SOCKS_TIMEOUT = 120


def _environment() -> Environment:
    return Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )


def torrc_directives() -> set[str]:
    """
    Returns:
        The first word of every static line the torrc template emits.
    """
    tree = _environment().parse(read_text(str(TORRC)))
    return {
        line.split()[0]
        for data in tree.find_all(nodes.TemplateData)
        for line in data.data.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def rendered_env(key: str) -> str:
    """
    Args:
        key: a key of the probe's env template.

    Returns:
        The value its line renders to.
    """
    (line,) = [
        line
        for line in read_text(str(TEST_ENV)).splitlines()
        if line.startswith(f"{key}=")
    ]
    return _environment().from_string(line).render().partition("=")[2]


class TestOnionPortWindow(unittest.TestCase):
    def test_an_attempt_outlasts_tors_socks_timeout(self) -> None:
        self.assertIn("SocksPort", torrc_directives())
        self.assertNotIn(
            "SocksTimeout",
            torrc_directives(),
            "torrc now sets SocksTimeout; ONION_PORT_TIMEOUT has to be derived "
            "from it instead of from Tor's default",
        )
        self.assertGreater(
            int(rendered_env("ONION_PORT_TIMEOUT")),
            TOR_DEFAULT_SOCKS_TIMEOUT,
            "a port probe attempt that ends before Tor's SocksTimeout walks away "
            "from a rendezvous Tor is still building, and Tor never reaches its "
            "own verdict or logs it",
        )


if __name__ == "__main__":
    unittest.main()
