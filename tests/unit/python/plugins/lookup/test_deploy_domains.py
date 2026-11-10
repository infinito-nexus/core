import unittest
from unittest import mock

from ansible.errors import AnsibleError

from plugins.lookup.deploy_domains import LookupModule
from utils.preflight.context import DeployClosureContext

MODULE = "plugins.lookup.deploy_domains"
DOMAINS = {
    "web-app-matomo": ["matomo.example.org", "matomo.abc.onion"],
    "web-app-nextcloud": {"canonical": "cloud.example.org"},
}


def _context():
    return DeployClosureContext(
        roles=["svc-db-mariadb", "web-app-matomo", "web-app-nextcloud"],
        applications={},
        config=mock.Mock(),
        lookup=lambda name, role, default: DOMAINS.get(role, default),
    )


class TestDeployDomainsLookup(unittest.TestCase):
    def _run(self, terms, side_effect=None):
        with mock.patch(
            f"{MODULE}.deploy_closure_context",
            return_value=_context(),
            side_effect=side_effect,
        ):
            return LookupModule().run(terms, variables={})

    def test_the_clearnet_domains_of_every_closure_role_are_listed(self):
        self.assertEqual(
            self._run([["web-app-matomo"]]),
            [["cloud.example.org", "matomo.example.org"]],
        )

    def test_a_closure_error_becomes_an_ansible_error(self):
        with self.assertRaises(AnsibleError):
            self._run([[]], side_effect=TypeError("x"))

    def test_a_wrong_term_count_is_rejected(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run([[], []])


if __name__ == "__main__":
    unittest.main()
