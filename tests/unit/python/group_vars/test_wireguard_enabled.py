import unittest
from pathlib import Path
from typing import ClassVar

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml

_WIREGUARD_VARS = Path(PROJECT_ROOT) / "group_vars" / "all" / "21_wireguard.yml"


class TestWireguardEnabled(unittest.TestCase):
    env: ClassVar[Environment]
    source: ClassVar[str]

    @classmethod
    def setUpClass(cls):
        cls.env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
        cls.source = load_yaml(_WIREGUARD_VARS)["WIREGUARD_ENABLED"]

    def _render(self, *groups: str) -> str:
        return self.env.from_string(self.source).render(group_names=list(groups))

    def test_a_host_in_the_wireguard_group_runs_it(self):
        self.assertEqual("True", self._render("svc-swarm-node", "svc-net-wireguard"))

    def test_a_host_outside_the_group_stays_untouched(self):
        self.assertEqual("False", self._render("svc-swarm-node", "web-app-a"))
