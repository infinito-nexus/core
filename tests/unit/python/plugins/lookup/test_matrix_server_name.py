"""Unit tests for the matrix_server_name lookup plugin.

Pins the one choice every Matrix user id depends on: which network's name the
homeserver answers to. An onion deployment runs Synapse under the Tor node, so
a user id built on the clearnet name matches no account there, and the reverse
publishes an unreachable contact handle on a clearnet deployment.
"""

from __future__ import annotations

import importlib.util
import unittest
import unittest.mock as mock

from . import PROJECT_ROOT

MODULE = "lookup_matrix_server_name"
CLEARNET = "matrix.example.com"
ONION = "jq3cxczghznig7mzqbfy7jlznvi4pv7q53xul2ptvrnsosnfamkhjrid.onion"
TOR_NODE = "matrix." + ONION


def _load_lookup():
    spec = importlib.util.spec_from_file_location(
        MODULE, str(PROJECT_ROOT / "plugins/lookup/matrix_server_name.py")
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _StubLookup:
    def __init__(self, result):
        self._result = result

    def run(self, terms, variables=None):
        return [self._result]


class TestResolveServerName(unittest.TestCase):
    def _resolve(self, module, domain, tor_node, server_name):
        def get(name, loader=None, templar=None):
            if name == "domain":
                return _StubLookup(domain)

            class _Config:
                def run(self, terms, variables=None):
                    role = terms[0]
                    return [tor_node if role == module.TOR_ROLE else server_name]

            return _Config()

        with mock.patch.object(module, "lookup_loader", mock.Mock(get=get)):
            return module.resolve_server_name({}, None, None)

    def test_an_onion_deployment_answers_under_the_tor_node(self) -> None:
        module = _load_lookup()

        self.assertEqual(
            self._resolve(module, "matrix." + ONION, TOR_NODE, CLEARNET), TOR_NODE
        )

    def test_a_clearnet_deployment_keeps_the_declared_name(self) -> None:
        module = _load_lookup()

        self.assertEqual(self._resolve(module, CLEARNET, TOR_NODE, CLEARNET), CLEARNET)

    def test_an_onion_domain_without_a_tor_node_falls_back_rather_than_empty(
        self,
    ) -> None:
        module = _load_lookup()

        self.assertEqual(
            self._resolve(module, "matrix." + ONION, "", CLEARNET), CLEARNET
        )


if __name__ == "__main__":
    unittest.main()
