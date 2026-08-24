import unittest

from plugins.filter.active_docker import (
    FilterModule,
    active_docker_container_count,
)


class TestActiveDockerFilter(unittest.TestCase):
    def setUp(self):
        self.group_names = [
            "web-app-jira",
            "web-app-confluence",
            "svc-db-postgres",
            "svc-ai-ollama",
            "web-svc-cdn",
            "unrelated-group",
        ]

        self.apps = {
            "web-app-jira": {
                "services": {
                    "jira": {"enabled": True},
                    "proxy": {},
                    "debug": {"enabled": False},
                }
            },
            "web-app-confluence": {
                "services": {
                    "confluence": {"enabled": True},
                }
            },
            "svc-db-postgres": {
                "services": {
                    "postgres": {"enabled": True},
                    "backup": {"enabled": False},
                }
            },
            "svc-ai-ollama": {
                "services": {
                    "ollama": "ghcr.io/ollama/ollama:latest",
                }
            },
            "web-svc-cdn": {
                "services": {
                    "cdn": {"enabled": "yes"},
                }
            },
            "db-core-mariadb": {"services": {"mariadb": {"enabled": True}}},
            "web-app-gitlab": {"services": {"gitlab": {"enabled": True}}},
            "web-app-empty": {},
        }

    def test_basic_count(self):
        cnt = active_docker_container_count(self.apps, self.group_names)
        self.assertEqual(cnt, 6)

    def test_filter_module_registration(self):
        fm = FilterModule().filters()
        self.assertIn("active_docker_container_count", fm)
        cnt = fm["active_docker_container_count"](self.apps, self.group_names)
        self.assertEqual(cnt, 6)

    def test_prefix_regex_override(self):
        cnt = active_docker_container_count(
            self.apps, self.group_names, prefix_regex=r"^svc-.*"
        )
        self.assertEqual(cnt, 2)

    def test_not_in_group_names_excluded(self):
        apps = dict(self.apps)
        apps["web-app-pixelfed"] = {"services": {"pix": {"enabled": True}}}
        cnt = active_docker_container_count(apps, self.group_names)
        self.assertEqual(cnt, 6)

    def test_missing_services_and_non_mapping(self):
        self.assertEqual(active_docker_container_count(None, self.group_names), 0)
        self.assertEqual(
            active_docker_container_count(None, self.group_names, ensure_min_one=True),
            1,
        )

        cnt = active_docker_container_count(self.apps, self.group_names)
        self.assertEqual(cnt, 6)

    def test_enabled_false_excluded(self):
        apps = dict(self.apps)
        apps["web-app-jira"]["services"]["only_false"] = {"enabled": False}
        cnt = active_docker_container_count(apps, self.group_names)
        self.assertEqual(cnt, 6)  # unchanged

    def test_enabled_truthy_string_included(self):
        apps = dict(self.apps)
        apps["web-app-confluence"]["services"]["extra"] = {"enabled": "true"}
        cnt = active_docker_container_count(apps, self.group_names)
        self.assertEqual(cnt, 7)

    def test_ensure_min_one(self):
        apps = {
            "web-app-foo": {"services": {"s": {"enabled": False}}},
        }
        cnt0 = active_docker_container_count(apps, ["web-app-foo"])
        cnt1 = active_docker_container_count(apps, ["web-app-foo"], ensure_min_one=True)
        self.assertEqual(cnt0, 0)
        self.assertEqual(cnt1, 1)


if __name__ == "__main__":
    unittest.main()
