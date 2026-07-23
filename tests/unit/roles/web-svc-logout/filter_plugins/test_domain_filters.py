import importlib.util
import unittest

from . import PROJECT_ROOT

# Path to the actual plugin under roles/web-svc-logout/filter_plugins
DOMAIN_FILTERS_PATH = str(
    PROJECT_ROOT / "roles" / "web-svc-logout" / "filter_plugins" / "domain_filters.py"
)

# Dynamically load the domain_filters module
spec = importlib.util.spec_from_file_location("domain_filters", DOMAIN_FILTERS_PATH)
domain_filters = importlib.util.module_from_spec(spec)
spec.loader.exec_module(domain_filters)
FilterModule = domain_filters.FilterModule


class TestLogoutDomainsFilter(unittest.TestCase):
    def setUp(self):
        self.filter_fn = FilterModule().filters()["logout_domains"]

    def test_flatten_and_feature_flag(self):
        applications = {
            "app1": {
                "server": {"domains": {"canonical": "single.domain.com"}},
                "services": {"logout": {"enabled": True}},
            },
            "app2": {
                "server": {"domains": {"canonical": ["list1.com", "list2.com"]}},
                "services": {"logout": {"enabled": True}},
            },
            "app3": {
                "server": {
                    "domains": {"canonical": {"k1": "dictA.com", "k2": "dictB.com"}}
                },
                "services": {"logout": {"enabled": True}},
            },
            "app4": {
                "server": {"domains": {"canonical": "no-logout.com"}},
                "services": {"logout": {"enabled": False}},
            },
            "other": {
                "server": {"domains": {"canonical": "ignored.com"}},
                "services": {"logout": {"enabled": True}},
            },
        }
        group_names = ["app1", "app2", "app3", "app4"]
        result = set(self.filter_fn(applications, group_names))
        expected = {
            "single.domain.com",
            "list1.com",
            "list2.com",
            "dictA.com",
            "dictB.com",
        }
        self.assertEqual(result, expected)

    def test_missing_canonical_defaults_empty(self):
        applications = {
            "app1": {
                "server": {"domains": {}},  # no 'canonical' key
                "services": {"logout": {"enabled": True}},
            }
        }
        group_names = ["app1"]
        self.assertEqual(self.filter_fn(applications, group_names), [])

    def test_app_not_in_group(self):
        applications = {
            "app1": {
                "server": {"domains": {"canonical": "domain.com"}},
                "services": {"logout": {"enabled": True}},
            }
        }
        group_names = []
        self.assertEqual(self.filter_fn(applications, group_names), [])

    def test_invalid_domain_type(self):
        applications = {
            "app1": {
                "server": {"domains": {"canonical": 123}},
                "services": {"logout": {"enabled": True}},
            }
        }
        group_names = ["app1"]
        self.assertEqual(self.filter_fn(applications, group_names), [123])

    def test_onion_page_drops_clearnet_only_app(self):
        applications = {
            "web-svc-logout": {"services": {"logout": {"enabled": True}}},
            "web-app-seaweedfs": {"services": {"logout": {"enabled": True}}},
            "web-app-nextcloud": {"services": {"logout": {"enabled": True}}},
        }
        domains = {
            "web-svc-logout": ["logout.abc.onion"],
            "web-app-seaweedfs": {
                "api": "api.s3.example",
                "filer": "filer.s3.example",
                "master": "master.s3.example",
            },
            "web-app-nextcloud": ["nc.abc.onion"],
        }
        result = self.filter_fn(applications, list(applications), domains=domains)
        self.assertEqual(set(result), {"logout.abc.onion", "nc.abc.onion"})

    def test_clearnet_page_drops_onion_domains(self):
        applications = {
            "web-svc-logout": {"services": {"logout": {"enabled": True}}},
            "app1": {"services": {"logout": {"enabled": True}}},
        }
        domains = {
            "web-svc-logout": ["logout.example"],
            "app1": ["app.example", "app.abc.onion"],
        }
        result = self.filter_fn(applications, list(applications), domains=domains)
        self.assertEqual(set(result), {"logout.example", "app.example"})

    def test_dual_family_app_swept_on_same_family(self):
        applications = {
            "web-svc-logout": {"services": {"logout": {"enabled": True}}},
            "app1": {"services": {"logout": {"enabled": True}}},
        }
        domains = {
            "web-svc-logout": ["logout.abc.onion"],
            "app1": ["app.abc.onion", "app.example"],
        }
        result = self.filter_fn(applications, list(applications), domains=domains)
        self.assertEqual(set(result), {"logout.abc.onion", "app.abc.onion"})

    def test_disabled_entity_keys_excluded(self):
        applications = {
            "web-svc-logout": {"services": {"logout": {"enabled": True}}},
            "web-app-seaweedfs": {
                "services": {
                    "logout": {"enabled": True},
                    "frontend": {"enabled": False, "domains": ["filer", "master"]},
                }
            },
        }
        domains = {
            "web-svc-logout": ["logout.example"],
            "web-app-seaweedfs": {
                "api": "api.s3.example",
                "filer": "filer.s3.example",
                "master": "master.s3.example",
            },
        }
        result = self.filter_fn(applications, list(applications), domains=domains)
        self.assertEqual(set(result), {"logout.example", "api.s3.example"})


if __name__ == "__main__":
    unittest.main()
