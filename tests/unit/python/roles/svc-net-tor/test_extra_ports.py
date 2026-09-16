"""The node onion forwards HTTP whether or not the proxy is in the inventory.

``lookup('tor_ports')`` collects what the roles in ``group_names`` declare under
``ports.onion``. Port 80 belongs to ``svc-prx-openresty``, which a node acquires
through ``sys-stk-front-proxy`` and which therefore appears in no dependency
list an inventory holds. A node provisioned with ``--include svc-net-tor`` alone
published an onion forwarding SSH and nothing else.

These run the real lookup over a stubbed ``tor_ports``, so a flag that stops
reaching the forward list, or a derived port that starts duplicating a flagged
one, fails here rather than on the node.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from typing import Any
from unittest import mock

from ansible.errors import AnsibleError

from . import PROJECT_ROOT

LOOKUP = "roles/svc-net-tor/lookup_plugins/tor_extra_ports.py"
SSH_ENTRY = {"onion_port": 22, "target": "127.0.0.1:22"}
HTTP_ENTRY = {"onion_port": 80, "target": "127.0.0.1:80"}
ENABLED = {"TOR_ONION_SSH_ENABLED": True, "TOR_ONION_HTTP_ENABLED": True}


def _load_lookup():
    path = PROJECT_ROOT / LOOKUP
    spec = importlib.util.spec_from_file_location("tor_extra_ports_lookup", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["tor_extra_ports_lookup"] = module
    spec.loader.exec_module(module)
    return module


class _DerivedPorts:
    """Stands in for the tor_ports lookup the plugin composes with."""

    def __init__(self, entries: list[dict[str, Any]]):
        self.entries = entries

    def run(self, _terms, **_kwargs):
        return [self.entries]


class TestExtraPorts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_lookup()

    def _ports(self, derived: list[dict], **variables) -> list[dict]:
        lookup = self.module.LookupModule()
        lookup._templar = None
        lookup._loader = None
        with mock.patch.object(
            self.module.lookup_loader, "get", return_value=_DerivedPorts(derived)
        ):
            return lookup.run([], variables={**ENABLED, **variables})[0]

    def test_http_is_forwarded_without_the_proxy_in_the_inventory(self) -> None:
        self.assertIn(
            HTTP_ENTRY,
            self._ports([]),
            "a node whose inventory lists only svc-net-tor still serves its apps "
            "over the onion, so the forward cannot depend on the proxy being listed",
        )

    def test_a_derived_port_does_not_duplicate_a_flagged_one(self) -> None:
        ports = self._ports([HTTP_ENTRY])
        self.assertEqual(
            [entry for entry in ports if entry["onion_port"] == 80],
            [HTTP_ENTRY],
            "torrc writes one HiddenServicePort line per entry, so a duplicate "
            "publishes the same forward twice",
        )

    def test_derived_ports_still_reach_the_forward_list(self) -> None:
        onion_dns = {"onion_port": 9053, "target": "127.0.0.1:9053"}
        self.assertIn(
            onion_dns,
            self._ports([onion_dns]),
            "the flags add to what the services declare, they do not replace it",
        )

    def test_a_flag_turns_its_forward_off(self) -> None:
        ports = self._ports([], TOR_ONION_HTTP_ENABLED=False)
        self.assertNotIn(HTTP_ENTRY, ports)
        self.assertIn(SSH_ENTRY, ports, "the other flag is untouched")

    def test_an_undeclared_flag_is_refused(self) -> None:
        lookup = self.module.LookupModule()
        lookup._templar = None
        with self.assertRaises(AnsibleError) as raised:
            lookup.run([], variables={"TOR_ONION_SSH_ENABLED": True})
        self.assertIn("TOR_ONION_HTTP_ENABLED", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
