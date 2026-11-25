from __future__ import annotations

import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from plugins.lookup import role_subnet_exceptions
from plugins.lookup.role_subnet_exceptions import LookupModule, outside_pool_roles


def _app(local):
    return {"networks": {"local": local}}


APPLICATIONS = {
    "web-app-openpost": _app({"subnet": "192.88.99.0/24", "outside_pool": True}),
    "web-app-bigbluebutton": _app({"subnet": "10.7.7.0/24", "outside_pool": True}),
    "web-app-pooled": _app({"subnet": "192.168.10.0/24", "outside_pool": False}),
    "web-app-plain": _app({"subnet": "192.168.11.0/24"}),
    "svc-without-networks": {},
}


class TestOutsidePoolRoles(unittest.TestCase):
    def test_only_the_flagged_roles_in_sorted_order(self):
        self.assertEqual(
            outside_pool_roles(APPLICATIONS),
            ["web-app-bigbluebutton", "web-app-openpost"],
        )

    def test_a_flag_that_is_not_a_boolean_fails(self):
        with self.assertRaises(AnsibleError):
            outside_pool_roles({"web-app-x": _app({"outside_pool": "yes"})})


class TestLookup(unittest.TestCase):
    def test_reads_the_merged_applications(self):
        with mock.patch.object(role_subnet_exceptions, "lookup_loader") as loader:
            loader.get.return_value = mock.MagicMock(
                run=mock.MagicMock(return_value=[APPLICATIONS])
            )
            result = LookupModule().run([], variables={})

        self.assertEqual(result, [["web-app-bigbluebutton", "web-app-openpost"]])
        self.assertEqual(loader.get.call_args.args, ("applications",))

    def test_rejects_terms(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run(["unexpected"], variables={})


if __name__ == "__main__":
    unittest.main()
