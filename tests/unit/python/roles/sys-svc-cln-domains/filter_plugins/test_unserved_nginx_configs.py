import importlib.util
import unittest

from . import PROJECT_ROOT


def _load_filter():
    path = (
        PROJECT_ROOT
        / "roles"
        / "sys-svc-cln-domains"
        / "filter_plugins"
        / "unserved_nginx_configs.py"
    )
    spec = importlib.util.spec_from_file_location("unserved_nginx_configs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.unserved_nginx_configs


SERVED = [
    "dashboard.example.org",
    "example.org",
    "legacy.example",
    "*.legacy.example",
]


class TestUnservedNginxConfigs(unittest.TestCase):
    def setUp(self):
        self.unserved = _load_filter()

    def test_a_domain_the_host_no_longer_serves_is_removed(self):
        found = [
            "/etc/nginx/servers/https/social.legacy.example.conf",
            "/etc/nginx/servers/http/wheel.example.org.conf",
        ]
        self.assertEqual(
            self.unserved(found, SERVED),
            [
                "/etc/nginx/servers/http/wheel.example.org.conf",
                "/etc/nginx/servers/https/social.legacy.example.conf",
            ],
        )

    def test_every_served_domain_and_the_wildcard_keep_their_config(self):
        found = [
            "/etc/nginx/servers/https/dashboard.example.org.conf",
            "/etc/nginx/servers/http/example.org.conf",
            "/etc/nginx/servers/https/legacy.example.conf",
            "/etc/nginx/servers/https/*.legacy.example.conf",
        ]
        self.assertEqual(self.unserved(found, SERVED), [])

    def test_files_not_named_after_a_domain_are_kept(self):
        found = [
            "/etc/nginx/servers/default.conf",
            "/etc/nginx/servers/https/_.conf",
            "/etc/nginx/servers/https/old.example.org.conf.bak",
        ]
        self.assertEqual(self.unserved(found, SERVED), [])

    def test_onion_services_are_kept(self):
        found = ["/etc/nginx/servers/http/abcdef0123456789.onion.conf"]
        self.assertEqual(self.unserved(found, SERVED), [])

    def test_matching_ignores_case(self):
        found = ["/etc/nginx/servers/https/Dashboard.Example.org.conf"]
        self.assertEqual(self.unserved(found, ["DASHBOARD.example.ORG"]), [])


if __name__ == "__main__":
    unittest.main()
