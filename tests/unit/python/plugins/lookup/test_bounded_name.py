import unittest
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError

from plugins.lookup.bounded_name import LookupModule

ONION = "x.wiki." + "a" * 56 + ".onion"


class TestBoundedNameLookup(unittest.TestCase):
    def setUp(self):
        self.lookup = LookupModule()

        def _get(name, *args, **kwargs):
            plugin = MagicMock()

            def _run(terms, variables=None, **_kwargs):
                return [(variables or {}).get("domains", {})]

            plugin.run.side_effect = _run
            return plugin

        self._patchers = [
            patch("plugins.lookup.bounded_name.lookup_loader.get", side_effect=_get),
            patch(
                "plugins.lookup.bounded_name.get_domain",
                side_effect=lambda domains, app: domains[app],
            ),
            patch(
                "plugins.lookup.bounded_name.get_entity_name",
                side_effect=lambda app: app.rsplit("-", 1)[-1],
            ),
        ]
        for p in self._patchers:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patchers])

    def _run(self, domain, limit, app="web-app-xwiki"):
        return self.lookup.run([app, limit], variables={"domains": {app: domain}})[0]

    def test_a_fitting_domain_is_kept(self):
        self.assertEqual(self._run("wiki.example.org", 63), "wiki.example.org")

    def test_a_domain_at_the_limit_is_kept(self):
        self.assertEqual(self._run("a" * 27, 27), "a" * 27)

    def test_a_longer_domain_falls_back_to_the_entity(self):
        self.assertEqual(self._run(ONION, 63), "xwiki")
        self.assertEqual(self._run("a" * 28, 27), "xwiki")

    def test_an_empty_domain_falls_back_to_the_entity(self):
        self.assertEqual(self._run("", 63), "xwiki")

    def test_bad_arity_raises(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["web-app-xwiki"], variables={})

    def test_an_empty_application_raises(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["  ", 63], variables={})

    def test_a_non_positive_or_non_integer_limit_raises(self):
        for limit in (0, -1, "many"):
            with self.subTest(limit=limit), self.assertRaises(AnsibleError):
                self.lookup.run(["web-app-xwiki", limit], variables={})


if __name__ == "__main__":
    unittest.main()
