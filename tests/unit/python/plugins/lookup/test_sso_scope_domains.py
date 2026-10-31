import unittest
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError

from plugins.lookup.sso_cookie_domains import LookupModule as CookieLookup
from plugins.lookup.sso_whitelist_domains import LookupModule as WhitelistLookup

ONION = "ocickgnpp2fqow4ku7juiprpdvwiq6ufv7j3jfykgnzvoe32jeasg5qd.onion"
CLEARNET = "infinito.test"

IDP = {"web-app-keycloak": ["auth." + CLEARNET]}
IDP_ONION = {"web-app-keycloak": ["auth." + ONION]}


def _loader(module):
    """Patch the lookup_loader of *module* so 'domains' and 'config' read the
    scope variables the test supplies.

    Args:
        module: dotted path of the lookup module under test.
    """

    def _get(name, *args, **kwargs):
        plugin = MagicMock()

        def _run(terms, variables=None, **_kwargs):
            variables = variables or {}
            if name == "domains":
                return [variables.get("domains", {})]
            return [variables.get("tor_node", "")]

        plugin.run.side_effect = _run
        return plugin

    return patch(f"{module}.lookup_loader.get", side_effect=_get)


class TestSsoCookieDomains(unittest.TestCase):
    def setUp(self):
        self.lookup = CookieLookup()
        patcher = _loader("plugins.lookup.sso_cookie_domains")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, app_id, domains):
        return self.lookup.run([app_id], variables={"domains": domains})[0]

    def test_single_clearnet_host_keeps_its_exact_name(self):
        out = self._run("web-app-a", {"web-app-a": ["a." + CLEARNET], **IDP})
        self.assertEqual(out, ["a." + CLEARNET, "auth." + CLEARNET])

    def test_multi_host_app_collapses_to_the_shared_parent(self):
        out = self._run(
            "web-app-a",
            {
                "web-app-a": {
                    "filer": "filer.seaweedfs.s3." + CLEARNET,
                    "master": "master.seaweedfs.s3." + CLEARNET,
                },
                **IDP,
            },
        )
        self.assertEqual(out, ["seaweedfs.s3." + CLEARNET, "auth." + CLEARNET])

    def test_onion_only_app_scopes_the_onion_parent(self):
        out = self._run(
            "web-app-a",
            {
                "web-app-a": {
                    "filer": "filer.seaweedfs.s3." + ONION,
                    "master": "master.seaweedfs.s3." + ONION,
                },
                **IDP_ONION,
            },
        )
        self.assertEqual(out, ["seaweedfs.s3." + ONION, "auth." + ONION])

    def test_dual_stack_app_scopes_both_families(self):
        out = self._run(
            "web-app-a",
            {"web-app-a": ["a." + CLEARNET, "a." + ONION], **IDP},
        )
        self.assertEqual(out, ["a." + CLEARNET, "a." + ONION, "auth." + CLEARNET])

    def test_app_without_domains_yields_no_scope(self):
        self.assertEqual(self._run("web-app-a", IDP), [])

    def test_term_count_is_enforced(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run([], variables={"domains": {}})


class TestSsoWhitelistDomains(unittest.TestCase):
    def setUp(self):
        self.lookup = WhitelistLookup()
        patcher = _loader("plugins.lookup.sso_whitelist_domains")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, app_id, domains, tor_node=ONION, primary=CLEARNET):
        return self.lookup.run(
            [app_id],
            variables={
                "domains": domains,
                "tor_node": tor_node,
                "DOMAIN_PRIMARY": primary,
            },
        )[0]

    def test_clearnet_app_whitelists_the_primary_domain(self):
        out = self._run("web-app-a", {"web-app-a": ["a." + CLEARNET]})
        self.assertEqual(out, ["." + CLEARNET])

    def test_onion_app_whitelists_only_the_node_onion(self):
        out = self._run("web-app-a", {"web-app-a": ["a." + ONION]})
        self.assertEqual(out, ["." + ONION])

    def test_dual_stack_app_whitelists_both(self):
        out = self._run("web-app-a", {"web-app-a": ["a." + CLEARNET, "a." + ONION]})
        self.assertEqual(out, ["." + CLEARNET, "." + ONION])

    def test_onion_host_without_a_provisioned_node_is_not_whitelisted(self):
        out = self._run("web-app-a", {"web-app-a": ["a." + ONION]}, tor_node="")
        self.assertEqual(out, [])

    def test_clearnet_host_without_a_primary_domain_raises(self):
        with self.assertRaises(AnsibleError):
            self._run("web-app-a", {"web-app-a": ["a." + CLEARNET]}, primary="")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
