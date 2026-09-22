"""The rendered test.env survives the shell that sources it.

test-e2e-cli loads test.env with ``set -a && . test.env && set +a``. An unquoted
space-separated value there is not an assignment but a command with a one-word
environment prefix: ``ONION_PORTS=25 80`` runs ``80``, bash reports
``command not found`` and carries on, and the probe reads an empty port list as
nothing to check.
"""

from __future__ import annotations

import subprocess
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from plugins.filter.dotenv import FilterModule
from utils.cache.files import read_text

from . import PROJECT_ROOT

TEMPLATE = PROJECT_ROOT / "roles" / "svc-net-tor" / "templates" / "test.env.j2"
PORTS = [25, 80, 587]


def _lookup(name: str, *_args: str) -> object:
    return {
        "config": "example.onion",
        "nginx": "/etc/nginx/conf.d/servers",
        "tor_ports": [
            {"onion_port": port, "target": f"127.0.0.1:{port}"} for port in PORTS
        ],
        "tor_socks": "127.0.0.1:9050",
    }[name]


def _render(mode: str) -> str:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters.update(FilterModule().filters())
    return env.from_string(read_text(str(TEMPLATE))).render(
        lookup=_lookup,
        DEPLOYMENT_MODE=mode,
        TOR_DNSMASQ_CONF="/etc/dnsmasq.d/tor-onion.conf",
    )


class TestTestEnvSourcing(unittest.TestCase):
    def test_every_onion_port_reaches_the_probe(self) -> None:
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        (
                            "set -a && . /dev/stdin && set +a && "
                            'printf %s "${ONION_PORTS-unset}"'
                        ),
                    ],
                    input=_render(mode),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    result.stderr, "", "sourcing test.env must not run anything"
                )
                self.assertEqual(result.stdout, " ".join(str(port) for port in PORTS))


if __name__ == "__main__":
    unittest.main()
