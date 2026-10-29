import copy
import unittest

from plugins.filter.security_headers import FilterModule
from utils.cache.yaml import load_yaml
from utils.roles.applications.security_headers import security_headers

from . import PROJECT_ROOT

PLATFORM = {
    "nosniff": False,
    "referrer_policy": "",
    "permissions_policy": "",
    "hsts": {"max_age": 31536000, "include_subdomains": False, "preload": False},
}


def apps_with(override):
    """Return an applications map whose one app declares *override*.

    Args:
        override: the app's ``server.security_headers`` block.
    """
    return {"web-app-x": {"server": {"security_headers": override}}}


class TestPlatformValues(unittest.TestCase):
    def test_an_app_without_a_block_gets_the_platform_values(self):
        apps = {"web-app-plain": {"server": {"status_codes": {"default": [200]}}}}
        self.assertEqual(
            security_headers(apps, "web-app-plain", PLATFORM),
            {
                "nosniff": False,
                "referrer_policy": "",
                "permissions_policy": "",
                "hsts": "max-age=31536000",
            },
        )

    def test_a_redirect_vhost_passes_its_domain_and_gets_the_platform_values(self):
        result = security_headers(apps_with({"nosniff": True}), "old.example", PLATFORM)
        self.assertFalse(result["nosniff"])
        self.assertEqual(result["hsts"], "max-age=31536000")

    def test_the_repository_platform_values_are_valid(self):
        platform = load_yaml(PROJECT_ROOT / "group_vars/all/04_webserver.yml")[
            "WEBSERVER_SECURITY_HEADERS"
        ]
        self.assertEqual(
            security_headers({}, "web-app-plain", platform)["hsts"],
            "max-age=31536000",
        )

    def test_an_incomplete_platform_block_fails(self):
        platform = copy.deepcopy(PLATFORM)
        del platform["hsts"]["preload"]
        with self.assertRaisesRegex(ValueError, "preload"):
            security_headers({}, "web-app-plain", platform)

    def test_the_platform_block_is_not_mutated(self):
        platform = copy.deepcopy(PLATFORM)
        security_headers(
            apps_with({"hsts": {"include_subdomains": True}}), "web-app-x", platform
        )
        self.assertEqual(platform, PLATFORM)


class TestOverrides(unittest.TestCase):
    def test_an_override_replaces_only_its_own_keys(self):
        result = security_headers(
            apps_with({"nosniff": True, "hsts": {"include_subdomains": True}}),
            "web-app-x",
            PLATFORM,
        )
        self.assertTrue(result["nosniff"])
        self.assertEqual(result["referrer_policy"], "")
        self.assertEqual(result["hsts"], "max-age=31536000; includeSubDomains")

    def test_preload_follows_include_subdomains(self):
        result = security_headers(
            apps_with({"hsts": {"include_subdomains": True, "preload": True}}),
            "web-app-x",
            PLATFORM,
        )
        self.assertEqual(result["hsts"], "max-age=31536000; includeSubDomains; preload")

    def test_a_referrer_policy_list_is_accepted(self):
        value = "no-referrer, strict-origin-when-cross-origin"
        result = security_headers(
            apps_with({"referrer_policy": value}), "web-app-x", PLATFORM
        )
        self.assertEqual(result["referrer_policy"], value)

    def test_a_permissions_policy_keeps_its_quoted_origins(self):
        value = 'camera=(self "https://meet.example.org"), microphone=(self)'
        result = security_headers(
            apps_with({"permissions_policy": value}), "web-app-x", PLATFORM
        )
        self.assertEqual(result["permissions_policy"], value)


class TestRejections(unittest.TestCase):
    def assert_rejected(self, override, pattern, error=ValueError):
        with self.assertRaisesRegex(error, pattern):
            security_headers(apps_with(override), "web-app-x", PLATFORM)

    def test_an_unknown_key_fails(self):
        self.assert_rejected({"nosnif": True}, "unknown keys")

    def test_an_unknown_hsts_key_fails(self):
        self.assert_rejected({"hsts": {"subdomains": True}}, "unknown keys")

    def test_a_non_mapping_block_fails(self):
        self.assert_rejected(None, "must be a mapping", TypeError)

    def test_a_string_flag_fails(self):
        self.assert_rejected({"nosniff": "yes"}, "must be bool", TypeError)

    def test_a_boolean_max_age_fails(self):
        self.assert_rejected({"hsts": {"max_age": True}}, "must be int", TypeError)

    def test_a_negative_max_age_fails(self):
        self.assert_rejected({"hsts": {"max_age": -1}}, "negative")

    def test_preload_without_include_subdomains_fails(self):
        self.assert_rejected({"hsts": {"preload": True}}, "requires include_subdomains")

    def test_preload_with_a_short_max_age_fails(self):
        self.assert_rejected(
            {"hsts": {"max_age": 86400, "include_subdomains": True, "preload": True}},
            "at least 31536000",
        )

    def test_an_unknown_referrer_policy_token_fails(self):
        self.assert_rejected(
            {"referrer_policy": "strict-origin-when-cross-orgin"},
            "unknown policy tokens",
        )

    def test_a_line_break_in_a_header_value_fails(self):
        self.assert_rejected(
            {"permissions_policy": "camera=()\r\nSet-Cookie: x=1"},
            "printable ASCII",
        )


class TestFilterModule(unittest.TestCase):
    def test_filter_is_registered(self):
        self.assertIs(FilterModule().filters()["security_headers"], security_headers)


if __name__ == "__main__":
    unittest.main()
