"""coturn pins its addresses only on host networking in compose mode, and only addresses the host owns.

Pinned, coturn listens on ``networks.internet.ip4``, on loopback for the
healthcheck and on ``networks.internet.ip6``, and relays on
``networks.internet.ip4`` instead of on whichever Docker bridge address the
allocation happens to land on. coturn exits when it cannot bind a listening
address, and a pinned coturn stops answering on every address it was not
given. So the command is pinned only when the host carries ip4 and either
carries ip6 as written or ip6 is unset (empty or the ``defaults_networks``
placeholder); any other host keeps the unpinned command the role rendered
before, instead of losing its IPv6 listener or failing to bind.

The real ``vars/main.yml`` is resolved by Ansible's templar and the real
``compose.yml.j2`` is rendered with the role's lookups stubbed, so a broken
ownership check or a gate that leaks into bridge or swarm mode fails here.
"""

from __future__ import annotations

import re
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.filter.core import to_bool
from ansible.template import Templar
from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles/web-svc-coturn"
TEMPLATE = ROLE / ROLE_FILE_TEMPL_COMPOSE
VARS = ROLE / ROLE_FILE_VARS_MAIN
NETWORK_DEFAULTS = DataLoader().load_from_file(
    str(PROJECT_ROOT / "group_vars/all/08_networks.yml")
)["defaults_networks"]
PLACEHOLDER_IP6 = NETWORK_DEFAULTS["internet"]["ip6"]

IP4 = "198.51.100.7"
IP6 = "2001:db8:1::2"
FOREIGN_IP4 = "203.0.113.7"
FOREIGN_IP6 = "2001:db8:ffff::9"
LOOPBACK = "127.0.0.1"

OWNED = {
    "all_ipv4_addresses": [IP4, "172.17.0.1", "192.168.101.1"],
    "all_ipv6_addresses": [IP6, "fe80::1"],
}

RESOLVED = (
    "COTURN_LOOPBACK_IP",
    "COTURN_RELAY_IP",
    "COTURN_ADDRESSES_PINNED",
    "COTURN_LISTENING_IPS",
)

STUBBED = {
    "application_id": "web-svc-coturn",
    "entity_name": "coturn",
    "COTURN_CONTAINER": "coturn",
    "COTURN_USER_AUTH_ENABLED": False,
    "COTURN_TOTAL_QUOTA": 2000,
    "COTURN_STUN_TURN_PORT": 3481,
    "COTURN_STUN_TURN_PORT_TLS": 5351,
    "COTURN_RELAY_PORT_START": 20000,
    "COTURN_RELAY_PORT_END": 39999,
    "COTURN_TLS_ENABLED": True,
    "COTURN_TLS_CERT_PATH": "/etc/coturn/cert.pem",
    "COTURN_TLS_KEY_PATH": "/etc/coturn/key.pem",
    "DOCKER_BIND_HOST": LOOPBACK,
}

INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": "services:\n",
    "roles/sys-svc-container/templates/base.yml.j2": "",
}

_HEALTHCHECK = re.compile(r"turnutils_stunclient -p \d+ (\S+) \|\| nc -z (\S+) \d+")


def render(
    *,
    ip4: str = IP4,
    ip6: str = IP6,
    facts: dict | None = None,
    mode: str = "compose",
    network: str = "host",
) -> str:
    """The coturn compose file for one deployment.

    Args:
        ip4: ``networks.internet.ip4``.
        ip6: ``networks.internet.ip6``.
        facts: the host's ``ansible_facts``; ``None`` means a host owning ``OWNED``.
        mode: ``DEPLOYMENT_MODE``.
        network: ``services.coturn.network_mode``.
    """
    inputs = {
        "networks": {"internet": {"ip4": ip4, "ip6": ip6, "dns": ""}},
        "defaults_networks": NETWORK_DEFAULTS,
        "ansible_facts": OWNED if facts is None else facts,
        "DEPLOYMENT_MODE": mode,
        "COTURN_NETWORK_MODE": network,
    }
    declared = DataLoader().load_from_file(str(VARS), trusted_as_template=True)
    templar = Templar(loader=DataLoader(), variables={**declared, **inputs})
    values = {name: templar.template(declared[name]) for name in RESOLVED}

    env = Environment(
        autoescape=select_autoescape(default_for_string=False),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        loader=DictLoader(INCLUDES),
    )
    env.filters["bool"] = to_bool
    env.globals["lookup"] = lambda *_args, **_kwargs: ""
    return env.from_string(read_text(str(TEMPLATE))).render(
        **STUBBED, **inputs, **values
    )


def listening(rendered: str) -> list[str]:
    return re.findall(r"--listening-ip=(\S+)", rendered)


def relay(rendered: str) -> list[str]:
    return re.findall(r"--relay-ip=(\S+)", rendered)


class TestOwnedAddressesArePinned(unittest.TestCase):
    def test_listeners_cover_ip4_loopback_and_ip6(self) -> None:
        self.assertEqual(listening(render()), [IP4, LOOPBACK, IP6])

    def test_relays_stay_on_ip4(self) -> None:
        self.assertEqual(
            relay(render()),
            [IP4],
            "without the pin coturn may place a relay on a Docker bridge "
            "address and still announce the external IP for it",
        )

    def test_the_healthcheck_probes_a_pinned_listener(self) -> None:
        rendered = render()
        probed = _HEALTHCHECK.search(rendered)
        self.assertIsNotNone(probed, "the healthcheck command changed shape")
        for address in probed.groups():
            self.assertIn(
                address,
                listening(rendered),
                "a pinned coturn answers only on its listening addresses, so a "
                "probe aimed elsewhere marks a healthy server unhealthy",
            )


class TestAnUnsetIpv6IsLeftOut(unittest.TestCase):
    def test_the_placeholder_is_left_out(self) -> None:
        rendered = render(ip6=PLACEHOLDER_IP6)
        self.assertEqual(
            (listening(rendered), relay(rendered)), ([IP4, LOOPBACK], [IP4])
        )

    def test_an_empty_ipv6_is_left_out(self) -> None:
        rendered = render(ip6="")
        self.assertEqual(
            (listening(rendered), relay(rendered)), ([IP4, LOOPBACK], [IP4])
        )


class TestAddressesTheHostLacksKeepTheUnpinnedCommand(unittest.TestCase):
    def test_a_foreign_ipv6(self) -> None:
        rendered = render(ip6=FOREIGN_IP6)
        self.assertEqual(
            (listening(rendered), relay(rendered)),
            ([], []),
            "pinning ip4 alone would drop the IPv6 listener the unpinned "
            "command still had",
        )

    def test_an_ipv6_written_unlike_the_interface_lists_it(self) -> None:
        rendered = render(ip6=IP6.upper())
        self.assertEqual((listening(rendered), relay(rendered)), ([], []))

    def test_a_foreign_ipv4_keeps_the_unpinned_command(self) -> None:
        rendered = render(ip4=FOREIGN_IP4)
        self.assertEqual(
            (listening(rendered), relay(rendered)),
            ([], []),
            "a 1:1-NAT host carries its public IPv4 nowhere, so pinning it "
            "stops coturn from binding at all",
        )

    def test_a_host_without_address_facts_keeps_the_unpinned_command(self) -> None:
        rendered = render(facts={})
        self.assertEqual((listening(rendered), relay(rendered)), ([], []))


class TestOtherModesAreUnchanged(unittest.TestCase):
    def test_bridge_and_swarm_never_pin(self) -> None:
        for mode, network in (
            ("compose", "bridge"),
            ("swarm", "host"),
            ("swarm", "bridge"),
        ):
            with self.subTest(mode=mode, network=network):
                rendered = render(mode=mode, network=network)
                self.assertEqual((listening(rendered), relay(rendered)), ([], []))


if __name__ == "__main__":
    unittest.main()
