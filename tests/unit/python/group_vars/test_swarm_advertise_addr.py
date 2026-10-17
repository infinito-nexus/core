import unittest
from pathlib import Path
from typing import ClassVar

from jinja2 import Environment, StrictUndefined, select_autoescape

import plugins.lookup.mesh_address as mesh_address
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml

_SWARM_VARS = Path(PROJECT_ROOT) / "group_vars" / "all" / "18_swarm.yml"


def _lookup(hostvars):
    def lookup(name, *terms):
        if name != "mesh_address":
            raise AssertionError(f"unexpected lookup({name!r})")
        plugin = mesh_address.LookupModule()
        return plugin.run(list(terms), variables={"hostvars": hostvars})[0]

    return lookup


class TestSwarmAdvertiseAddr(unittest.TestCase):
    env: ClassVar[Environment]
    source: ClassVar[str]

    @classmethod
    def setUpClass(cls):
        cls.env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
        cls.env.filters["bool"] = lambda value: str(value).lower() in ("true", "1")
        cls.source = load_yaml(_SWARM_VARS)["swarm"]["manager"]["advertise_addr"]

    def _render(self, *, enabled=True, interfaces=None):
        applications = (
            {}
            if interfaces is None
            else {"svc-net-wireguard": {"networks": {"interfaces": interfaces}}}
        )
        hostvars = {"mgr": {"applications": applications}}
        return (
            self.env.from_string(self.source)
            .render(
                WIREGUARD_ENABLED=enabled, STACK_HOST="mgr", lookup=_lookup(hostvars)
            )
            .strip()
        )

    @staticmethod
    def _interface(name, address, primary):
        return {"name": name, "host": "mgr", "address": address, "primary": primary}

    def test_a_mesh_this_repository_never_named_is_followed(self):
        interfaces = [
            self._interface("alpha", "10.100.10.1", True),
            self._interface("beta", "10.100.11.1", False),
        ]
        self.assertEqual(self._render(interfaces=interfaces), "10.100.10.1")

    def test_the_primary_wins_over_the_order_on_disk(self):
        interfaces = [
            self._interface("data", "10.100.1.1", False),
            self._interface("swarm", "10.100.0.1", True),
        ]
        self.assertEqual(self._render(interfaces=interfaces), "10.100.0.1")

    def test_no_mesh_leaves_swarm_on_its_default(self):
        self.assertEqual(self._render(enabled=False), "")
        self.assertEqual(self._render(interfaces=[]), "")
