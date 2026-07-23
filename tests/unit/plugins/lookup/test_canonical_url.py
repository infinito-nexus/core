import unittest
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError

from plugins.lookup.canonical_url import LookupModule


class TestCanonicalUrlLookup(unittest.TestCase):
    def setUp(self):
        self.lookup = LookupModule()
        self.base_vars = {"TLS_ENABLED": True}

        def _get(name, *args, **kwargs):
            plugin = MagicMock()

            def _run(terms, variables=None, **_kwargs):
                key = "domains" if name == "domains" else "applications"
                return [(variables or {}).get(key, {})]

            plugin.run.side_effect = _run
            return plugin

        patcher = patch(
            "plugins.lookup.canonical_url.lookup_loader.get",
            side_effect=_get,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, terms, domains, applications=None, extra_vars=None, **kwargs):
        v = dict(self.base_vars)
        v["domains"] = domains
        v["applications"] = applications or {}
        if extra_vars:
            v.update(extra_vars)
        return self.lookup.run(terms, variables=v, **kwargs)[0]

    def test_primary_clearnet_is_https(self):
        out = self._run(["web-app-a"], {"web-app-a": ["a.example"]})
        self.assertEqual(out, "https://a.example")

    def test_primary_onion_is_http(self):
        out = self._run(["web-app-a"], {"web-app-a": ["a.abc.onion"]})
        self.assertEqual(out, "http://a.abc.onion")

    def test_named_canonical_clearnet(self):
        out = self._run(
            ["web-app-matrix", "element"],
            {
                "web-app-matrix": {
                    "synapse": "matrix.example",
                    "element": "element.example",
                }
            },
        )
        self.assertEqual(out, "https://element.example")

    def test_named_canonical_onion(self):
        out = self._run(
            ["web-app-matrix", "synapse"],
            {
                "web-app-matrix": {
                    "synapse": "matrix.abc.onion",
                    "element": "element.abc.onion",
                }
            },
        )
        self.assertEqual(out, "http://matrix.abc.onion")

    def test_missing_key_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(
                ["web-app-matrix", "nope"],
                {"web-app-matrix": {"element": "element.example"}},
            )

    def test_key_on_list_domain_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(["web-app-a", "element"], {"web-app-a": ["a.example"]})

    def test_bad_arity_raises(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run([], variables=self.base_vars)

    def test_primary_aligns_to_clearnet_consumer(self):
        out = self._run(
            ["web-svc-cdn"],
            {
                "web-svc-cdn": ["cdn.abc.onion", "cdn.example"],
                "web-app-bigbluebutton": ["bbb.example"],
            },
            extra_vars={"application_id": "web-app-bigbluebutton"},
        )
        self.assertEqual(out, "https://cdn.example")

    def test_primary_stays_onion_for_onion_consumer(self):
        out = self._run(
            ["web-svc-cdn"],
            {
                "web-svc-cdn": ["cdn.abc.onion", "cdn.example"],
                "web-app-dashboard": ["dash.abc.onion"],
            },
            extra_vars={"application_id": "web-app-dashboard"},
        )
        self.assertEqual(out, "http://cdn.abc.onion")

    def test_primary_onion_only_falls_back_for_clearnet_consumer(self):
        out = self._run(
            ["web-svc-cdn"],
            {
                "web-svc-cdn": ["cdn.abc.onion"],
                "web-app-bigbluebutton": ["bbb.example"],
            },
            extra_vars={"application_id": "web-app-bigbluebutton"},
        )
        self.assertEqual(out, "http://cdn.abc.onion")

    def test_primary_unchanged_without_consumer_context(self):
        out = self._run(
            ["web-svc-cdn"],
            {
                "web-svc-cdn": ["cdn.abc.onion", "cdn.example"],
                "web-app-bigbluebutton": ["bbb.example"],
            },
        )
        self.assertEqual(out, "http://cdn.abc.onion")

    def test_consumer_kwarg_drives_alignment(self):
        out = self._run(
            ["web-svc-cdn"],
            {
                "web-svc-cdn": ["cdn.abc.onion", "cdn.example"],
                "web-app-bigbluebutton": ["bbb.example"],
            },
            applications={
                "web-app-bigbluebutton": {"services": {"cdn": {"enabled": True}}}
            },
            consumer="web-app-bigbluebutton",
        )
        self.assertEqual(out, "https://cdn.example")

    def test_consumer_with_enabled_binding_resolves(self):
        out = self._run(
            ["web-app-seaweedfs", "filer"],
            {"web-app-seaweedfs": {"filer": "filer.example"}},
            applications={
                "web-app-nextcloud": {"services": {"seaweedfs": {"enabled": True}}}
            },
            consumer="web-app-nextcloud",
        )
        self.assertEqual(out, "https://filer.example")

    def test_consumer_with_disabled_binding_is_empty(self):
        out = self._run(
            ["web-app-seaweedfs", "filer"],
            {"web-app-seaweedfs": {"filer": "filer.example"}},
            applications={
                "web-app-nextcloud": {"services": {"seaweedfs": {"enabled": False}}}
            },
            consumer="web-app-nextcloud",
        )
        self.assertEqual(out, "")

    def test_consumer_without_binding_is_empty(self):
        out = self._run(
            ["web-app-seaweedfs", "filer"],
            {"web-app-seaweedfs": {"filer": "filer.example"}},
            applications={"web-app-nextcloud": {"services": {}}},
            consumer="web-app-nextcloud",
        )
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
