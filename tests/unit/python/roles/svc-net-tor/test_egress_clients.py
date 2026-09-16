"""The egress guard admits every address a container can come from.

The guard drops any source outside ``tor_egress_clients``, and containers reach
the TransPort and the DNSPort through exactly those rules. So the list is not a
convenience: if it ever stops covering docker's own address pools, every
container loses the resolver and the transparent proxy at once, and it fails in
production rather than here.

This runs the real lookup over the repository's real network declarations. A
narrowed pool, a renamed key or a dropped entry in the lookup all surface as a
failure of the property the rules depend on.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from unittest import mock

import jinja2

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

NETWORKS = PROJECT_ROOT / "group_vars/all/08_networks.yml"
LOOKUP = "roles/svc-net-tor/lookup_plugins/tor_egress_clients.py"


def _load_lookup():
    path = PROJECT_ROOT / LOOKUP
    spec = importlib.util.spec_from_file_location("tor_egress_clients_lookup", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["tor_egress_clients_lookup"] = module
    spec.loader.exec_module(module)
    return module


class _Templar:
    """Resolves the group_vars cross-references the lookup renders."""

    def __init__(self, variables: dict):
        self.available_variables = variables

    def template(self, value):
        return (
            jinja2.Environment(autoescape=False)  # noqa: S701 - renders CIDRs, not markup
            .from_string(str(value))
            .render(**self.available_variables)
        )


class TestEgressClients(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_lookup()
        cls.variables = load_yaml_any(str(NETWORKS))

    def _admitted(self) -> list[str]:
        lookup = self.module.LookupModule()
        lookup._templar = _Templar(self.variables)
        lookup._loader = mock.MagicMock()
        with mock.patch.object(self.module, "lookup_loader") as loader:
            loader.get.return_value = mock.MagicMock(
                run=mock.MagicMock(return_value=[[]])
            )
            return lookup.run([], variables=self.variables)[0]

    def test_every_docker_address_pool_is_admitted(self) -> None:
        admitted = self._admitted()
        pools = self.variables["NETWORK_DOCKER_ADDRESS_POOLS"]
        self.assertTrue(pools, "no docker address pool is declared")
        for pool in pools:
            with self.subTest(pool=pool["base"]):
                self.assertIn(
                    pool["base"],
                    admitted,
                    "containers draw their address from this pool and reach the "
                    "guarded ports through the guard, so dropping it from the "
                    "admitted list takes the resolver away from every container",
                )

    def test_loopback_is_admitted(self) -> None:
        """The host resolves .onion through its own loopback."""
        self.assertIn(self.variables["NETWORK_LOOPBACK_CIDR"], self._admitted())

    def test_the_lan_is_not_admitted_wholesale(self) -> None:
        """The guarded ports carry no access policy, so the LAN is not a client.

        Admitting 10.0.0.0/8 would hand a transparent proxy and a resolver to
        every host the operator's network happens to contain.
        """
        self.assertNotIn(
            self.variables["NETWORK_PRIVATE_CIDRS"]["class_a"], self._admitted()
        )


if __name__ == "__main__":
    unittest.main()
