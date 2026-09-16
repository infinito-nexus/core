"""Every port the egress router binds locally is dropped for foreign sources.

The guard chain is the only thing between these listeners and anyone who can
route a packet to the node. A port that is bound but not named in a drop rule
answers the whole reachable network: the transparent proxy relays, the DNSPort
resolves, and the split-DNS forwarder both resolves recursively and hands out
the node's own ``.onion`` records.

This walks the real declaration chain rather than a fixture: ``meta/services.yml``
names the ports tor itself binds, ``vars/main.yml`` turns each into a
``TOR_*_PORT`` variable, and the guard list plus the fragment template spend
those variables on drop rules. A port added to the service declaration without a
rule fails the first test.

The forwarder sits outside that chain because it is not tor's own port: it takes
the well-known resolver port from ``NETWORK_DNS_PORT``, and the host already
assigns that number to whichever resolver owns it. The second test covers it by
name instead.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles/svc-net-tor"
SERVICES = ROLE / ROLE_FILE_META_SERVICES
VARS = ROLE / ROLE_FILE_VARS_MAIN
FRAGMENT = ROLE / "templates/nftables.conf.j2"

_VARIABLE = re.compile(r"\{\{\s*([A-Z][A-Z0-9_]*)\s*\}\}")
_PORT_KEY = re.compile(r"services\.tor\.ports\.local\.([a-z0-9_]+)")
_DROP_RULE = re.compile(r"^\s*(?!#).*\b(?P<protocol>tcp|udp)\s+dport\b.*\bdrop\b")


def _declared_ports() -> dict[str, int]:
    return load_yaml_any(str(SERVICES))["tor"]["ports"]["local"]


def _port_variables() -> dict[str, str]:
    """Maps each ``TOR_*_PORT`` variable to the port key it reads."""
    declared = load_yaml_any(str(VARS))
    names = {}
    for name, value in declared.items():
        if not isinstance(value, str):
            continue
        key = _PORT_KEY.search(value)
        if key is not None:
            names[name] = key.group(1)
    return names


def _entries_for(variable: str) -> list[dict]:
    """Guard entries whose port comes from *variable*."""
    return [
        entry
        for entry in load_yaml_any(str(VARS))["TOR_EGRESS_GUARDED_PORTS"]
        if _VARIABLE.search(str(entry["port"])).group(1) == variable
    ]


def _guarded_keys() -> set[str]:
    """Port keys that reach a drop rule, through the vars list or the template."""
    variables = _port_variables()
    guarded: set[str] = set()

    for entry in load_yaml_any(str(VARS))["TOR_EGRESS_GUARDED_PORTS"]:
        name = _VARIABLE.search(str(entry["port"]))
        if name is not None and name.group(1) in variables:
            guarded.add(variables[name.group(1)])

    for line in read_text(str(FRAGMENT)).splitlines():
        if _DROP_RULE.match(line) is None:
            continue
        for name in _VARIABLE.findall(line):
            if name in variables:
                guarded.add(variables[name])

    return guarded


class TestGuardedPorts(unittest.TestCase):
    def test_every_locally_bound_port_reaches_a_drop_rule(self) -> None:
        declared = _declared_ports()
        self.assertTrue(declared, f"{SERVICES} declares no local ports")

        unguarded = sorted(set(declared) - _guarded_keys())
        self.assertEqual(
            unguarded,
            [],
            "these ports are bound on the node but no guard rule drops a "
            "foreign source for them, so they answer everything that can route "
            f"to the node: {', '.join(f'{key} ({declared[key]})' for key in unguarded)}",
        )

    def test_the_forwarder_is_guarded_on_both_transports(self) -> None:
        entries = _entries_for("TOR_DNSMASQ_PORT")
        self.assertEqual(
            {entry["protocol"] for entry in entries},
            {"tcp", "udp"},
            "dnsmasq answers on both transports, and a TCP query returns the "
            "same records a UDP one does",
        )

    def test_the_forwarder_admits_every_source_the_node_calls_internal(self) -> None:
        """The resolver may not be stricter than the proxy it sits next to.

        ``internal`` is ``NETWORK_INTERNAL_CIDRS``, the same list ``torrc.j2``
        spends on ``SocksPolicy accept``. ``containers`` is narrower: out of
        ``10.0.0.0/8`` it carries only the docker pool and the exception role,
        which leaves out swarm's ingress network and every overlay docker
        allocates without an ipam block. Guarding the resolver with the narrow
        set hands a source a full SOCKS proxy and refuses it a name lookup.
        """
        self.assertEqual(
            {entry["admitted"] for entry in _entries_for("TOR_DNSMASQ_PORT")},
            {"internal"},
            "the resolver carries ordinary name resolution for everything the "
            "node routes, so it takes the internal set, not the container pools",
        )


if __name__ == "__main__":
    unittest.main()
