from __future__ import annotations

import unittest

from utils.roles.applications.services.database import (
    has_single_database_service,
    resolve_database_service_key,
)


class TestResolveDatabaseServiceKey(unittest.TestCase):
    def test_returns_key_when_one_enabled(self) -> None:
        apps = {"web-app-foo": {"services": {"mariadb": {"enabled": True}}}}
        self.assertEqual(resolve_database_service_key(apps, "web-app-foo"), "mariadb")

    def test_returns_empty_when_none_enabled(self) -> None:
        apps = {"web-app-foo": {"services": {"mariadb": {"enabled": False}}}}
        self.assertEqual(resolve_database_service_key(apps, "web-app-foo"), "")

    def test_raises_when_multiple_enabled(self) -> None:
        apps = {
            "svc-bkp-foo": {
                "services": {
                    "mariadb": {"enabled": True},
                    "postgres": {"enabled": True},
                }
            }
        }
        with self.assertRaises(ValueError) as ctx:
            resolve_database_service_key(apps, "svc-bkp-foo")
        self.assertIn("mariadb", str(ctx.exception))
        self.assertIn("postgres", str(ctx.exception))


class TestHasSingleDatabaseService(unittest.TestCase):
    def test_true_when_exactly_one_enabled(self) -> None:
        apps = {"web-app-foo": {"services": {"mariadb": {"enabled": True}}}}
        self.assertTrue(has_single_database_service(apps, "web-app-foo"))

    def test_false_when_none_enabled(self) -> None:
        apps = {"web-app-foo": {"services": {"mariadb": {"enabled": False}}}}
        self.assertFalse(has_single_database_service(apps, "web-app-foo"))

    def test_false_when_multiple_enabled(self) -> None:
        apps = {
            "svc-bkp-foo": {
                "services": {
                    "mariadb": {"enabled": True},
                    "postgres": {"enabled": True},
                }
            }
        }
        self.assertFalse(has_single_database_service(apps, "svc-bkp-foo"))

    def test_false_when_application_missing(self) -> None:
        self.assertFalse(has_single_database_service({}, "missing"))


if __name__ == "__main__":
    unittest.main()
