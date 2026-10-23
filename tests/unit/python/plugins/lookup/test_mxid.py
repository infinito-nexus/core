"""Unit tests for the mxid lookup plugin.

The filter pins the user-id shape and matrix_server_name pins which network's
name is used. What only this lookup can get wrong is joining the two, so that
is what these pin, including that it needs no role variable in scope.
"""

from __future__ import annotations

import importlib.util
import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from . import PROJECT_ROOT

MODULE = "lookup_mxid"
SERVER = "matrix.example.com"
ONION = "matrix.jq3cxczghznig7mzqbfy7jlznvi4pv7q53xul2ptvrnsosnfamkhjrid.onion"


def _load_lookup():
    spec = importlib.util.spec_from_file_location(
        MODULE, str(PROJECT_ROOT / "plugins/lookup/mxid.py")
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class TestMxidLookup(unittest.TestCase):
    def _run(self, module, terms, server, variables=None):
        instance = module.LookupModule()
        instance._templar = None
        instance._loader = None
        with mock.patch.object(module, "resolve_server_name", return_value=server):
            return instance.run(
                terms, variables=variables if variables is not None else {}
            )

    def test_the_server_name_is_resolved_and_never_an_argument(self) -> None:
        module = _load_lookup()

        self.assertEqual(
            self._run(module, ["administrator"], SERVER), ["@administrator:" + SERVER]
        )

    def test_an_onion_deployment_yields_an_onion_user_id(self) -> None:
        module = _load_lookup()

        self.assertEqual(
            self._run(module, ["chatgptbot"], ONION), ["@chatgptbot:" + ONION]
        )

    def test_no_role_variable_has_to_be_in_scope(self) -> None:
        module = _load_lookup()

        self.assertEqual(
            self._run(module, ["contact"], SERVER, {}), ["@contact:" + SERVER]
        )

    def test_more_than_one_term_is_refused(self) -> None:
        module = _load_lookup()
        instance = module.LookupModule()
        instance._templar = None
        instance._loader = None

        with self.assertRaises(AnsibleError):
            instance.run(["administrator", SERVER], variables={})


if __name__ == "__main__":
    unittest.main()
