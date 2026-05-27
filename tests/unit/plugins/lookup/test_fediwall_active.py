import importlib.util
import sys
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch


def _load_lookup_module() -> ModuleType:
    """Load the fediwall_active lookup plugin directly from the global
    plugins/lookup/ path. Stubs out ansible imports so the unit test
    does not require the ansible runtime."""

    # Stub minimal ansible.errors / ansible.plugins.lookup /
    # ansible.plugins.loader so the plugin module imports cleanly.
    if "ansible" not in sys.modules:
        ansible_pkg = ModuleType("ansible")
        sys.modules["ansible"] = ansible_pkg

    if "ansible.errors" not in sys.modules:
        errors_mod = ModuleType("ansible.errors")

        class _AnsibleError(Exception):
            pass

        errors_mod.AnsibleError = _AnsibleError
        sys.modules["ansible.errors"] = errors_mod

    if "ansible.plugins" not in sys.modules:
        plugins_pkg = ModuleType("ansible.plugins")
        sys.modules["ansible.plugins"] = plugins_pkg

    if "ansible.plugins.lookup" not in sys.modules:
        lookup_mod = ModuleType("ansible.plugins.lookup")

        class _LookupBase:
            pass

        lookup_mod.LookupBase = _LookupBase
        sys.modules["ansible.plugins.lookup"] = lookup_mod

    if "ansible.plugins.loader" not in sys.modules:
        loader_mod = ModuleType("ansible.plugins.loader")
        loader_mod.lookup_loader = MagicMock()
        sys.modules["ansible.plugins.loader"] = loader_mod

    from . import PROJECT_ROOT

    plugin_path = PROJECT_ROOT / "plugins" / "lookup" / "fediwall_active.py"
    spec = importlib.util.spec_from_file_location("fediwall_active", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestSelectActive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._module = _load_lookup_module()

    def test_returns_only_siblings_present_in_group_names(self):
        siblings = ["web-app-mastodon", "web-app-pixelfed", "web-app-friendica"]
        group_names = [
            "all",
            "web-app-mastodon",
            "web-app-friendica",
            "svc-db-postgres",
        ]
        self.assertEqual(
            type(self)._module.select_active(siblings, group_names),
            ["web-app-mastodon", "web-app-friendica"],
        )

    def test_preserves_input_order(self):
        siblings = ["web-app-friendica", "web-app-mastodon", "web-app-pixelfed"]
        group_names = ["web-app-mastodon", "web-app-pixelfed", "web-app-friendica"]
        self.assertEqual(
            type(self)._module.select_active(siblings, group_names),
            ["web-app-friendica", "web-app-mastodon", "web-app-pixelfed"],
        )

    def test_returns_empty_when_no_overlap(self):
        siblings = ["web-app-mastodon", "web-app-pixelfed"]
        group_names = ["all", "svc-db-postgres", "web-app-nextcloud"]
        self.assertEqual(type(self)._module.select_active(siblings, group_names), [])

    def test_returns_empty_when_siblings_is_empty(self):
        self.assertEqual(type(self)._module.select_active([], ["web-app-mastodon"]), [])

    def test_returns_empty_when_siblings_is_none(self):
        self.assertEqual(
            type(self)._module.select_active(None, ["web-app-mastodon"]), []
        )

    def test_returns_empty_when_group_names_is_empty(self):
        self.assertEqual(type(self)._module.select_active(["web-app-mastodon"], []), [])

    def test_returns_empty_when_group_names_is_none(self):
        self.assertEqual(
            type(self)._module.select_active(["web-app-mastodon"], None), []
        )

    def test_preserves_duplicates_in_siblings(self):
        siblings = ["web-app-mastodon", "web-app-mastodon"]
        group_names = ["web-app-mastodon"]
        self.assertEqual(
            type(self)._module.select_active(siblings, group_names),
            ["web-app-mastodon", "web-app-mastodon"],
        )


class TestResolveForWant(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._module = _load_lookup_module()
        cls._AnsibleError = sys.modules["ansible.errors"].AnsibleError

    def test_siblings_want_does_not_call_resolver(self):
        def boom(_):
            raise AssertionError("resolver must not be invoked for want='siblings'")

        out = type(self)._module.resolve_for_want(
            ["web-app-mastodon", "web-app-pixelfed"],
            ["web-app-mastodon"],
            "siblings",
            boom,
        )
        self.assertEqual(out, ["web-app-mastodon"])

    def test_url_bases_want_uses_resolver_per_active_sibling(self):
        siblings = ["web-app-mastodon", "web-app-pixelfed", "web-app-friendica"]
        group_names = ["web-app-mastodon", "web-app-friendica"]

        def resolver(s):
            return f"https://{s}.example/"

        out = type(self)._module.resolve_for_want(
            siblings, group_names, "url_bases", resolver
        )
        self.assertEqual(
            out,
            [
                "https://web-app-mastodon.example/",
                "https://web-app-friendica.example/",
            ],
        )

    def test_domains_want_uses_resolver_per_active_sibling(self):
        siblings = ["web-app-mastodon", "web-app-pixelfed"]
        group_names = ["web-app-pixelfed"]

        def resolver(s):
            return s.removeprefix("web-app-") + ".example"

        out = type(self)._module.resolve_for_want(
            siblings, group_names, "domains", resolver
        )
        self.assertEqual(out, ["pixelfed.example"])

    def test_returns_empty_when_no_active_sibling(self):
        out = type(self)._module.resolve_for_want(
            ["web-app-mastodon"],
            ["svc-db-postgres"],
            "url_bases",
            lambda _: "https://nope/",
        )
        self.assertEqual(out, [])

    def test_invalid_want_raises(self):
        with self.assertRaises(type(self)._AnsibleError):
            type(self)._module.resolve_for_want(
                ["web-app-mastodon"],
                ["web-app-mastodon"],
                "bogus",
                lambda s: s,
            )

    def test_resolver_required_for_non_siblings_want(self):
        with self.assertRaises(type(self)._AnsibleError):
            type(self)._module.resolve_for_want(
                ["web-app-mastodon"],
                ["web-app-mastodon"],
                "url_bases",
                None,
            )


class TestLookupModuleRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._module = _load_lookup_module()
        cls._AnsibleError = sys.modules["ansible.errors"].AnsibleError

    def _make_lookup(self):
        lookup = type(self)._module.LookupModule()
        lookup._templar = MagicMock()
        lookup._loader = MagicMock()
        return lookup

    def test_rejects_missing_term(self):
        lookup = self._make_lookup()
        with self.assertRaises(type(self)._AnsibleError):
            lookup.run([], variables={"group_names": []})

    def test_rejects_extra_terms(self):
        lookup = self._make_lookup()
        with self.assertRaises(type(self)._AnsibleError):
            lookup.run(["url_bases", "extra"], variables={"group_names": []})

    def test_rejects_unknown_want(self):
        lookup = self._make_lookup()
        with self.assertRaises(type(self)._AnsibleError):
            lookup.run(["bogus"], variables={"group_names": []})

    def test_siblings_want_returns_active_set_only(self):
        config = MagicMock()
        config.run.return_value = [
            ["web-app-mastodon", "web-app-pixelfed", "web-app-friendica"]
        ]
        with patch.object(type(self)._module.lookup_loader, "get", return_value=config):
            lookup = self._make_lookup()
            result = lookup.run(
                ["siblings"],
                variables={"group_names": ["web-app-mastodon", "web-app-friendica"]},
            )
        self.assertEqual(result, [["web-app-mastodon", "web-app-friendica"]])
        config.run.assert_called_once()

    def test_url_bases_want_calls_tls_lookup_per_active_sibling(self):
        config = MagicMock()
        config.run.return_value = [
            ["web-app-mastodon", "web-app-pixelfed", "web-app-friendica"]
        ]
        tls = MagicMock()
        tls.run.side_effect = [
            ["https://microblog.example/"],
            ["https://social.example/"],
        ]

        def fake_get(name, **_):
            if name == "config":
                return config
            if name == "tls":
                return tls
            raise AssertionError(f"unexpected lookup '{name}'")

        with patch.object(
            type(self)._module.lookup_loader, "get", side_effect=fake_get
        ):
            lookup = self._make_lookup()
            result = lookup.run(
                ["url_bases"],
                variables={"group_names": ["web-app-mastodon", "web-app-friendica"]},
            )

        self.assertEqual(
            result,
            [["https://microblog.example/", "https://social.example/"]],
        )
        self.assertEqual(tls.run.call_count, 2)
        called_with = [call.args[0] for call in tls.run.call_args_list]
        self.assertEqual(
            called_with,
            [
                ["web-app-mastodon", "url.base"],
                ["web-app-friendica", "url.base"],
            ],
        )

    def test_domains_want_calls_domain_lookup_per_active_sibling(self):
        config = MagicMock()
        config.run.return_value = [["web-app-mastodon", "web-app-pixelfed"]]
        domain = MagicMock()
        domain.run.side_effect = [["microblog.example"], ["photos.example"]]

        def fake_get(name, **_):
            if name == "config":
                return config
            if name == "domain":
                return domain
            raise AssertionError(f"unexpected lookup '{name}'")

        with patch.object(
            type(self)._module.lookup_loader, "get", side_effect=fake_get
        ):
            lookup = self._make_lookup()
            result = lookup.run(
                ["domains"],
                variables={"group_names": ["web-app-mastodon", "web-app-pixelfed"]},
            )
        self.assertEqual(result, [["microblog.example", "photos.example"]])

    def test_falls_back_to_templar_available_variables_when_variables_missing(self):
        config = MagicMock()
        config.run.return_value = [["web-app-mastodon"]]
        with patch.object(type(self)._module.lookup_loader, "get", return_value=config):
            lookup = self._make_lookup()
            lookup._templar.available_variables = {"group_names": ["web-app-mastodon"]}
            result = lookup.run(["siblings"], variables=None)
        self.assertEqual(result, [["web-app-mastodon"]])


if __name__ == "__main__":
    unittest.main()
