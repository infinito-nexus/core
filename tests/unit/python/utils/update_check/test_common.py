from __future__ import annotations

import unittest

from utils.update_check.common import pinned


def _keys(application_id, services):
    return [key for key, _ in pinned(application_id, {"services": services})]


class TestPinned(unittest.TestCase):
    def test_a_service_with_image_and_version_is_pinned(self):
        services = {"nextcloud": {"image": "nextcloud", "version": "34-fpm-alpine"}}
        self.assertEqual(_keys("web-app-nextcloud", services), ["nextcloud"])

    def test_a_service_without_version_is_not_pinned(self):
        services = {"proxy": {"image": "nginx"}}
        self.assertEqual(_keys("web-app-nextcloud", services), [])

    def test_a_service_without_image_is_not_pinned(self):
        services = {"cron": {"version": "34-fpm-alpine", "custom": True}}
        self.assertEqual(_keys("web-app-nextcloud", services), [])

    def test_a_disabled_service_is_not_pinned(self):
        services = {"talk": {"enabled": "False", "image": "talk", "version": "1"}}
        self.assertEqual(_keys("web-app-nextcloud", services), [])

    def test_a_shared_service_of_another_role_is_not_pinned(self):
        services = {"redis": {"shared": True, "image": "redis", "version": "8"}}
        self.assertEqual(_keys("web-app-nextcloud", services), [])

    def test_the_shared_primary_service_is_pinned(self):
        services = {"postgres": {"shared": True, "image": "postgres", "version": "18"}}
        self.assertEqual(_keys("svc-db-postgres", services), ["postgres"])


if __name__ == "__main__":
    unittest.main()
