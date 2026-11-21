from __future__ import annotations

import ipaddress
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import PROJECT_ROOT
from utils.meta.scan import iter_subnets
from utils.roles.mapping import ROLE_FILE_META_SERVICES

SERVICES = PROJECT_ROOT / "roles/web-app-openclaw" / ROLE_FILE_META_SERVICES
NETWORKS = PROJECT_ROOT / "group_vars/all/08_networks.yml"
MODES = {"compose": True, "swarm": False}


def _network_vars() -> dict:
    return DataLoader().load_from_file(str(NETWORKS), trusted_as_template=True)


def trusted_sources(compose: bool) -> list[ipaddress.IPv4Network]:
    """
    Args:
        compose: the value of IS_COMPOSE_MODE.

    Returns:
        The networks the gateway accepts a proxy connection from.
    """
    declared = DataLoader().load_from_file(str(SERVICES), trusted_as_template=True)
    variables = {**_network_vars(), "IS_COMPOSE_MODE": compose}
    rendered = Templar(loader=DataLoader(), variables=variables).template(
        declared["openclaw"]["config"]["trustedProxies"]
    )
    return [ipaddress.ip_network(str(cidr)) for cidr in rendered]


class TestTrustedProxySources(unittest.TestCase):
    def test_every_role_network_the_proxy_dials_from_is_trusted_in_each_mode(
        self,
    ) -> None:
        excepted = set(_network_vars()["NETWORK_ROLE_SUBNET_EXCEPTION_ROLES"])
        pinned = [
            (owner, subnet)
            for owner, subnet in iter_subnets()
            if owner.split(":", 1)[0] not in excepted
        ]
        self.assertTrue(pinned)
        for mode, compose in MODES.items():
            trusted = trusted_sources(compose)
            untrusted = [
                f"{owner} {subnet}"
                for owner, subnet in pinned
                if not any(subnet.subnet_of(source) for source in trusted)
            ]
            with self.subTest(mode=mode):
                self.assertEqual([], untrusted, f"trusted: {trusted}")


if __name__ == "__main__":
    unittest.main()
