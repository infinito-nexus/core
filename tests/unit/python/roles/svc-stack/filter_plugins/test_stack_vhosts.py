import importlib.util
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT


def _load_module():
    path = PROJECT_ROOT / "roles" / "svc-stack" / "filter_plugins" / "stack_vhosts.py"
    spec = importlib.util.spec_from_file_location("stack_vhosts", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


PRIMARY = "chat.example.org"
NAMED = {
    "api": "api.chat.example.org",
    "web": "chat.example.org",
    "view": "view.chat.example.org",
}
LISTED = ["social.example.org", "toot.example.org"]


class TestStackVhosts(unittest.TestCase):
    def setUp(self):
        self.module = _load_module()
        self.vhosts = self.module.stack_vhosts

    def test_a_role_without_vhosts_serves_its_primary_domain(self):
        expected = [{"key": "default", "domain": PRIMARY}]
        self.assertEqual(self.vhosts({}, PRIMARY, LISTED), expected)
        self.assertEqual(self.vhosts(None, PRIMARY, LISTED), expected)

    def test_the_default_key_serves_the_primary_domain_with_its_parameters(self):
        declared = {"default": {"client_max_body_size": "10G"}}
        self.assertEqual(
            self.vhosts(declared, PRIMARY, LISTED),
            [{"client_max_body_size": "10G", "key": "default", "domain": PRIMARY}],
        )

    def test_a_canonical_key_serves_its_canonical_domain(self):
        declared = {"api": {"http_port": 8001}, "view": None}
        self.assertEqual(
            self.vhosts(declared, PRIMARY, NAMED),
            [
                {"http_port": 8001, "key": "api", "domain": "api.chat.example.org"},
                {"key": "view", "domain": "view.chat.example.org"},
            ],
        )

    def test_vhosts_keep_their_declaration_order(self):
        declared = {"view": {}, "api": {}, "web": {}}
        self.assertEqual(
            [v["key"] for v in self.vhosts(declared, PRIMARY, NAMED)],
            ["view", "api", "web"],
        )

    def test_an_explicit_domain_overrides_the_key(self):
        declared = {
            "mail": {"domain": "mail.example.org", "flavour": "basic"},
            "webmail": {"domain": ["webmail.example.org"]},
        }
        self.assertEqual(
            self.vhosts(declared, PRIMARY, NAMED),
            [
                {"flavour": "basic", "key": "mail", "domain": "mail.example.org"},
                {"key": "webmail", "domain": "webmail.example.org"},
            ],
        )

    def test_the_canonical_selector_serves_every_canonical_domain(self):
        declared = {"default": {"domains": ["canonical"], "flavour": "ws_generic"}}
        self.assertEqual(
            self.vhosts(declared, PRIMARY, LISTED),
            [
                {
                    "flavour": "ws_generic",
                    "key": "default",
                    "domain": "social.example.org",
                },
                {
                    "flavour": "ws_generic",
                    "key": "default",
                    "domain": "toot.example.org",
                },
            ],
        )

    def test_the_canonical_selector_reads_the_values_of_named_domains(self):
        declared = {"default": {"domains": "canonical"}}
        self.assertEqual(
            [v["domain"] for v in self.vhosts(declared, PRIMARY, NAMED)],
            ["api.chat.example.org", "chat.example.org", "view.chat.example.org"],
        )

    def test_selectors_combine_canonical_and_served_domains(self):
        declared = {"default": {"domains": ["canonical", "served"]}}
        self.assertEqual(
            [
                v["domain"]
                for v in self.vhosts(
                    declared,
                    PRIMARY,
                    LISTED,
                    ["blog.example.org", "social.example.org"],
                )
            ],
            ["social.example.org", "toot.example.org", "blog.example.org"],
        )

    def test_the_primary_selector_serves_the_primary_domain(self):
        declared = {"default": {"domains": ["primary", "served"]}}
        self.assertEqual(
            [
                v["domain"]
                for v in self.vhosts(declared, PRIMARY, LISTED, ["b.example.org"])
            ],
            [PRIMARY, "b.example.org"],
        )

    def test_a_disabled_vhost_is_left_out(self):
        declared = {
            "api": {},
            "web": {"enabled": False},
            "view": {"enabled": "False"},
        }
        self.assertEqual(
            [v["key"] for v in self.vhosts(declared, PRIMARY, NAMED)], ["api"]
        )

    def test_an_enabled_string_keeps_the_vhost(self):
        declared = {"view": {"enabled": "True"}}
        self.assertEqual(
            self.vhosts(declared, PRIMARY, NAMED),
            [{"key": "view", "domain": "view.chat.example.org"}],
        )

    def test_a_domain_two_vhosts_name_is_served_once(self):
        declared = {"web": {"http_port": 1}, "default": {"http_port": 2}}
        self.assertEqual(
            self.vhosts(declared, PRIMARY, NAMED),
            [{"http_port": 1, "key": "web", "domain": PRIMARY}],
        )

    def test_a_key_without_a_canonical_domain_needs_a_domain(self):
        with self.assertRaisesRegex(AnsibleFilterError, "MUST declare 'domain'"):
            self.vhosts({"admin": {}}, PRIMARY, NAMED)

    def test_a_key_against_listed_domains_needs_a_domain(self):
        with self.assertRaisesRegex(AnsibleFilterError, "'api'"):
            self.vhosts({"api": {}}, PRIMARY, LISTED)

    def test_an_unknown_selector_is_an_error(self):
        with self.assertRaisesRegex(AnsibleFilterError, "unknown domains selector"):
            self.vhosts({"default": {"domains": ["aliases"]}}, PRIMARY, LISTED)

    def test_a_declaration_that_is_no_mapping_is_an_error(self):
        with self.assertRaisesRegex(AnsibleFilterError, "MUST be a mapping"):
            self.vhosts([{"domain": PRIMARY}], PRIMARY, LISTED)

    def test_the_filter_module_exports_the_filter(self):
        self.assertIs(self.module.FilterModule().filters()["stack_vhosts"], self.vhosts)


if __name__ == "__main__":
    unittest.main()
