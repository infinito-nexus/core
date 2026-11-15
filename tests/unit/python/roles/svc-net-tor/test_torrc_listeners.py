from __future__ import annotations

import itertools
import re
import unittest

from plugins.lookup.tor_socks import resolve_socks_endpoint
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT
from .test_egress_route import render

SERVICES = load_yaml_any(
    str(PROJECT_ROOT / "roles/svc-net-tor" / ROLE_FILE_META_SERVICES)
)
PORTS = SERVICES["tor"]["ports"]["local"]
APPLICATIONS = {"svc-net-tor": {"services": SERVICES}}
EGRESS = {
    "tor": {"include": [], "except": []},
    "direct": {"include": [], "except": []},
}
DOCKER0 = "172.17.0.1"
MODES = list(
    itertools.product(
        (False, True),
        (DOCKER0, ""),
        ("none", "onion", "all"),
        ("public", "chutney"),
        (True, False),
    )
)


def _lookup(name: str, *terms: str) -> str:
    return resolve_socks_endpoint(APPLICATIONS, *terms) if name == "tor_socks" else ""


def _render(name: str, swarm: bool, docker0: str, route: str, **overrides) -> str:
    return render(
        name,
        route,
        EGRESS,
        lookup=_lookup,
        IS_SWARM_MODE=swarm,
        TOR_NODE_BRIDGE=docker0,
        TOR_TRANS_PORT=PORTS["trans"],
        TOR_DNS_PORT=PORTS["dns"],
        **overrides,
    )


def listeners(torrc: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {
        keyword: [] for keyword in ("SocksPort", "TransPort", "DNSPort", "ControlPort")
    }
    for line in torrc.splitlines():
        keyword, _, value = line.partition(" ")
        if keyword in found:
            found[keyword].append(value)
    return found


def bound_hosts(docker0: str) -> list[str]:
    return ["127.0.0.1", DOCKER0] if docker0 else ["127.0.0.1"]


class TestTorrcListeners(unittest.TestCase):
    def test_every_mode_binds_exactly_where_its_consumers_connect(self) -> None:
        for swarm, docker0, route, flavor, guards in MODES:
            hosts = bound_hosts(docker0)
            routed = [] if route == "none" else hosts
            with self.subTest(
                swarm=swarm, docker0=docker0, route=route, flavor=flavor, guards=guards
            ):
                torrc = _render(
                    "torrc.j2",
                    swarm,
                    docker0,
                    route,
                    TOR_FLAVOR=flavor,
                    TOR_USE_ENTRY_GUARDS=guards,
                )
                self.assertEqual(
                    listeners(torrc),
                    {
                        "SocksPort": [f"{host}:{PORTS['socks']}" for host in hosts],
                        "TransPort": [f"{host}:{PORTS['trans']}" for host in routed],
                        "DNSPort": [f"{host}:{PORTS['dns']}" for host in routed],
                        "ControlPort": ["127.0.0.1:9051"],
                    },
                )

    def test_every_mode_runs_on_the_host_network_and_publishes_no_port(self) -> None:
        host_network = {
            False: 'network_mode: "host"',
            True: "hostnet:\n    external: true\n    name: host\n",
        }
        for swarm, route in itertools.product((False, True), ("none", "onion", "all")):
            with self.subTest(swarm=swarm, route=route):
                compose = _render("compose.yml.j2", swarm, DOCKER0, route)
                self.assertIn(host_network[swarm], compose)
                self.assertIsNone(re.search(r"^\s*ports:", compose, re.MULTILINE))


if __name__ == "__main__":
    unittest.main()
