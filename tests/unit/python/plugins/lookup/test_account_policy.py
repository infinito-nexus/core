import unittest
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.account_policy import LookupModule

POLICIES = {
    "web-app-a": {"username_max_length": 30, "username_pattern": "[a-z]+", "agent_reachable": True},
    "web-app-b": {"username_max_length": 15, "username_pattern": "[a-z]+", "agent_reachable": False},
}


class TestAccountPolicyLookup(unittest.TestCase):
    def setUp(self):
        patcher = patch(
            "plugins.lookup.account_policy.account_policy.load_policies",
            return_value=POLICIES,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_each_term_returns_its_derived_value(self):
        lookup = LookupModule()
        self.assertEqual(lookup.run(["username_max_length"]), [15])
        self.assertEqual(lookup.run(["account_max_length"]), [30])
        self.assertEqual(lookup.run(["username_patterns"]), [["[a-z]+"]])

    def test_an_unknown_or_missing_term_fails(self):
        lookup = LookupModule()
        with self.assertRaises(AnsibleError):
            lookup.run(["username_min_length"])
        with self.assertRaises(AnsibleError):
            lookup.run([])


if __name__ == "__main__":
    unittest.main()
