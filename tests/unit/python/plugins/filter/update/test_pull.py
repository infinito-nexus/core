from __future__ import annotations

import unittest
from unittest.mock import patch

from plugins.filter.update.pull import (
    FilterModule,
    update_pull_images,
    update_pull_summary,
)
from utils.update_check.common import FAIL, OK

DEPLOYED = [
    "svc-db-postgres",
    "svc-db-redis",
    "sys-ctl-x",
    "web-app-nextcloud",
    "web-app-wordpress",
]


def _applications():
    return {
        "svc-db-postgres": {
            "services": {
                "postgres": {
                    "image": "postgres",
                    "version": "18",
                    "shared": True,
                    "custom": True,
                }
            }
        },
        "svc-db-redis": {"services": {"redis": {"image": "redis", "version": "8"}}},
        "web-app-nextcloud": {
            "services": {
                "nextcloud": {
                    "image": "nextcloud",
                    "version": "34-fpm-alpine",
                    "custom": True,
                },
                "cron": {"custom": True},
                "whiteboard": {
                    "image": "ghcr.io/nextcloud-releases/whiteboard",
                    "version": "v1.5.9",
                    "custom": "nextcloud-whiteboard",
                },
                "proxy": {"image": "nginx", "version": "1.31.8"},
                "notify": {"image": "nginx"},
                "redis": {
                    "enabled": True,
                    "shared": True,
                    "image": "redis",
                    "version": "7",
                },
                "talk": {
                    "enabled": "False",
                    "image": "nextcloud/aio-talk",
                    "version": "latest",
                },
            }
        },
        "web-app-wordpress": {
            "services": {
                "wordpress": {"image": "wordpress", "version": "6.8"},
                "proxy": {"image": "nginx", "version": "1.31.8"},
            }
        },
        "web-app-unused": {"services": {"unused": {"image": "unused", "version": "1"}}},
    }


def _images():
    return update_pull_images(_applications(), DEPLOYED)


def _result(item, stdout="", **fields):
    return {"item": item, "failed": False, "stdout": stdout, **fields}


class TestUpdatePullImages(unittest.TestCase):
    def test_filters_are_registered(self):
        filters = FilterModule().filters()
        self.assertIs(filters["update_pull_images"], update_pull_images)
        self.assertIs(filters["update_pull_summary"], update_pull_summary)

    def test_every_pinned_image_of_a_deployed_role_is_pulled(self):
        self.assertEqual(
            _images()["pull"],
            [
                "ghcr.io/nextcloud-releases/whiteboard:v1.5.9",
                "nextcloud:34-fpm-alpine",
                "nginx:1.31.8",
                "postgres:18",
                "redis:8",
                "wordpress:6.8",
            ],
        )

    def test_the_base_of_a_locally_built_image_is_pulled(self):
        pull = _images()["pull"]
        self.assertIn("nextcloud:34-fpm-alpine", pull)
        self.assertIn("postgres:18", pull)

    def test_a_shared_service_another_role_provides_is_not_pulled(self):
        self.assertNotIn("redis:7", _images()["pull"])

    def test_a_disabled_service_is_not_pulled(self):
        self.assertNotIn("nextcloud/aio-talk:latest", _images()["pull"])

    def test_an_image_without_version_is_not_pulled(self):
        self.assertNotIn("nginx", _images()["pull"])

    def test_a_role_outside_the_closure_is_not_pulled(self):
        self.assertNotIn("unused:1", _images()["pull"])

    def test_an_image_two_roles_pin_is_pulled_once(self):
        self.assertEqual(_images()["pull"].count("nginx:1.31.8"), 1)

    def test_a_digest_pin_is_pulled_by_digest(self):
        applications = {
            "svc-db-redis": {
                "services": {"redis": {"image": "redis", "version": "sha256:abc"}}
            }
        }
        self.assertEqual(
            update_pull_images(applications, ["svc-db-redis"])["pull"],
            ["redis@sha256:abc"],
        )

    def test_built_lists_every_locally_built_image_with_its_roles(self):
        self.assertEqual(
            _images()["built"],
            [
                "nextcloud-whiteboard_custom (web-app-nextcloud)",
                "nextcloud_custom (web-app-nextcloud)",
                "postgres_custom (svc-db-postgres)",
            ],
        )

    def test_a_custom_service_without_a_name_fails(self):
        with (
            patch("plugins.filter.update.pull.get_entity_name", return_value=""),
            self.assertRaises(ValueError),
        ):
            _images()


class TestUpdatePullSummary(unittest.TestCase):
    def setUp(self):
        self.summary = update_pull_summary(
            [
                _result("nextcloud:34-fpm-alpine", "pulled\n"),
                _result("nginx:1.31.8", "present\n"),
                _result("postgres:18", "present\n"),
                _result(
                    "redis:8",
                    failed=True,
                    msg="non-zero return code",
                    stderr="Error response from daemon: manifest unknown\n",
                ),
            ],
            ["nextcloud_custom (web-app-nextcloud)"],
        )

    def test_the_first_line_counts_every_outcome(self):
        self.assertEqual(
            self.summary[0],
            f"⬇️ 1 pulled   {OK} 2 already present   "
            f"⏭️ 1 built by role   {FAIL} 1 failed",
        )

    def test_every_outcome_lists_its_images(self):
        self.assertIn("⬇️ pulled: nextcloud:34-fpm-alpine", self.summary)
        self.assertIn(f"{OK} already present: nginx:1.31.8, postgres:18", self.summary)
        self.assertIn(
            "⏭️ built by role: nextcloud_custom (web-app-nextcloud)", self.summary
        )

    def test_a_failed_pull_names_the_image_and_the_registry_error(self):
        self.assertIn(
            f"{FAIL} redis:8: Error response from daemon: manifest unknown",
            self.summary,
        )

    def test_a_failure_without_stderr_names_its_message(self):
        summary = update_pull_summary(
            [_result("redis:8", failed=True, msg="The task timed out")], []
        )
        self.assertIn(f"{FAIL} redis:8: The task timed out", summary)

    def test_unexpected_output_fails(self):
        with self.assertRaises(ValueError):
            update_pull_summary([_result("redis:8", "downloaded\n")], [])


if __name__ == "__main__":
    unittest.main()
