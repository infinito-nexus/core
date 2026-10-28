import unittest
from unittest import mock

from ansible.errors import AnsibleError

from plugins.lookup.package_batch import LookupModule
from utils.packages.schema import PackagesShapeError

MODULE = "plugins.lookup.package_batch"


class TestPackageBatchLookup(unittest.TestCase):
    def _run(self, terms, group_names, closure=None, side_effect=None):
        applications = mock.Mock()
        applications.run.return_value = [{"web-app-x": {}}]
        with (
            mock.patch(f"{MODULE}.lookup_loader.get", return_value=applications),
            mock.patch(f"{MODULE}.types_from_group_names", return_value=["server"]),
            mock.patch(
                f"{MODULE}.deploy_closure",
                return_value=closure or {"web-app-x"},
                side_effect=side_effect,
            ) as closure_mock,
            mock.patch(f"{MODULE}.batch_ids", return_value=["git"]) as ids_mock,
        ):
            lookup = LookupModule()
            result = lookup.run(terms, variables={"group_names": group_names})
        return result, closure_mock, ids_mock

    def test_returns_the_batch_ids_of_the_closure(self):
        result, _closure, ids = self._run([["web-app-x"]], ["web-app-x"])
        self.assertEqual(result, [["git"]])
        self.assertEqual(ids.call_args.args[0], {"web-app-x"})

    def test_nested_and_scalar_terms_become_one_seed_list(self):
        _result, closure, _ids = self._run([["web-app-x"], "role-b"], ["web-app-x"])
        self.assertEqual(closure.call_args.args[1], ["web-app-x", "role-b"])

    def test_the_host_groups_select_types_and_gates(self):
        _result, closure, _ids = self._run([["web-app-x"]], ["web-app-x", "servers"])
        self.assertEqual(closure.call_args.kwargs["host_types"], ["server"])
        self.assertEqual(
            closure.call_args.kwargs["group_names"], ["web-app-x", "servers"]
        )

    def test_a_registry_error_becomes_an_ansible_error(self):
        with self.assertRaises(AnsibleError):
            self._run([["web-app-x"]], [], side_effect=PackagesShapeError("broken"))


if __name__ == "__main__":
    unittest.main()
