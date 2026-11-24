from __future__ import annotations

import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from plugins.lookup import openpost_relay_domains as relay

SIBLINGS = {
    "mastodon": "web-app-mastodon",
    "pixelfed": "web-app-pixelfed",
    "peertube": "web-app-peertube",
}
DOMAINS = {
    "web-app-openpost": "publish.example",
    "web-app-mastodon": "microblog.example",
    "web-app-pixelfed": "picture.example",
    "web-app-peertube": "video.example",
}


class TestRelayDomains(unittest.TestCase):
    def test_own_domain_enabled_siblings_and_object_store_in_order(self):
        enabled = {"mastodon": True, "pixelfed": "False", "peertube": "true"}
        self.assertEqual(
            relay.relay_domains(
                "publish.example",
                SIBLINGS,
                enabled.__getitem__,
                DOMAINS.__getitem__,
                "s3.example",
            ),
            ["publish.example", "microblog.example", "video.example", "s3.example"],
        )

    def test_without_siblings_or_object_store_only_the_own_domain_remains(self):
        self.assertEqual(
            relay.relay_domains(
                "publish.example", SIBLINGS, lambda _: False, DOMAINS.__getitem__, ""
            ),
            ["publish.example"],
        )

    def test_a_flag_that_is_not_a_boolean_fails(self):
        with self.assertRaises(TypeError):
            relay.relay_domains(
                "publish.example", SIBLINGS, lambda _: "maybe", DOMAINS.__getitem__, ""
            )


class TestLookup(unittest.TestCase):
    def _run(self, objstore_enabled):
        answers = {
            ("config", "web-app-openpost", "services.relay.siblings"): SIBLINGS,
            ("config", "web-app-openpost", "services.mastodon.enabled"): True,
            ("config", "web-app-openpost", "services.pixelfed.enabled"): False,
            ("config", "web-app-openpost", "services.peertube.enabled"): False,
            ("objstore", "web-app-openpost", "enabled"): objstore_enabled,
            ("objstore", "web-app-openpost", "public_domain"): "s3.example",
        }

        def _get(name, **_):
            def _run(args, **__):
                if name == "domain":
                    return [DOMAINS[args[0]]]
                return [answers[(name, *args)]]

            return mock.MagicMock(run=_run)

        with mock.patch.object(relay, "lookup_loader") as loader:
            loader.get.side_effect = _get
            return relay.LookupModule().run([], variables={})

    def test_reads_siblings_flags_and_the_object_store(self):
        self.assertEqual(
            self._run(True),
            [["publish.example", "microblog.example", "s3.example"]],
        )

    def test_skips_the_object_store_when_openpost_uses_none(self):
        self.assertEqual(
            self._run(False), [["publish.example", "microblog.example"]]
        )

    def test_rejects_terms(self):
        with self.assertRaises(AnsibleError):
            relay.LookupModule().run(["unexpected"], variables={})


if __name__ == "__main__":
    unittest.main()
