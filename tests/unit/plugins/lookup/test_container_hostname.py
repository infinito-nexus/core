import unittest
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.container_hostname import LookupModule


class TestContainerHostnameLookup(unittest.TestCase):
    def setUp(self):
        self.lookup = LookupModule()

        def _domains_from_vars(*, variables=None, **_kwargs):
            return (variables or {}).get("domains", {})

        self._patchers = [
            patch(
                "plugins.lookup.container_hostname.get_merged_domains",
                side_effect=_domains_from_vars,
            ),
            patch(
                "plugins.lookup.container_hostname.get_domain",
                side_effect=lambda domains, app: domains[app],
            ),
            patch(
                "plugins.lookup.container_hostname.get_entity_name",
                side_effect=lambda app: app.rsplit("-", 1)[-1],
            ),
        ]
        for p in self._patchers:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patchers])

    def _run(self, app, domain):
        return self.lookup.run([app], variables={"domains": {app: domain}})[0]

    def test_short_domain_is_kept(self):
        self.assertEqual(
            self._run("web-app-xwiki", "wiki.example.org"), "wiki.example.org"
        )

    def test_long_onion_domain_falls_back_to_entity(self):
        onion = "x.wiki." + "a" * 56 + ".onion"
        self.assertEqual(self._run("web-app-xwiki", onion), "xwiki")

    def test_63_char_domain_is_kept(self):
        name = "a" * 63
        self.assertEqual(self._run("web-app-xwiki", name), name)

    def test_empty_domain_falls_back(self):
        self.assertEqual(self._run("web-app-xwiki", ""), "xwiki")

    def test_bad_arity_raises(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run([], variables={})

    def test_empty_app_raises(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["  "], variables={})


if __name__ == "__main__":
    unittest.main()
