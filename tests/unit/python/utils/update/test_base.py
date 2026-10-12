from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.base import (
    is_maintained,
    is_semver,
    latest_semver,
    version_depth,
    version_flavor,
    version_key,
)


class TestUpdateBase(unittest.TestCase):
    def test_latest_semver_respects_depth(self) -> None:
        tags = ["4", "4.5", "4.6", "4.5.1", "5"]

        self.assertEqual(latest_semver(tags, 1), "5")
        self.assertEqual(latest_semver(tags, 2), "4.6")
        self.assertEqual(latest_semver(tags, 3), "4.5.1")

    def test_is_semver_accepts_flavored_tag(self) -> None:
        self.assertTrue(is_semver("5.4.5-php8.3-apache"))
        self.assertTrue(is_semver("v1.2.3-alpha"))
        self.assertFalse(is_semver("main-v1.77.3.dynamic_rates"))
        self.assertFalse(is_semver("alpine"))

    def test_version_key_and_depth_ignore_flavor(self) -> None:
        self.assertEqual(version_key("5.4.5-php8.3-apache"), (5, 4, 5, 0))
        self.assertEqual(version_depth("5.4.5-php8.3-apache"), 3)
        self.assertEqual(version_flavor("5.4.5-php8.3-apache"), "-php8.3-apache")
        self.assertEqual(version_flavor("5.4.5"), "")

    def test_latest_semver_matches_flavor(self) -> None:
        tags = [
            "5.4.4-php8.3-apache",
            "5.4.5-php8.3-apache",
            "5.4.6-php8.3-apache",
            "5.4.6-php8.4-apache",
            "5.4.6-php8.3-fpm",
            "5.4.7",
            "alpine",
        ]

        self.assertEqual(
            latest_semver(tags, 3, "-php8.3-apache"),
            "5.4.6-php8.3-apache",
        )
        self.assertEqual(
            latest_semver(tags, 3, "-php8.4-apache"),
            "5.4.6-php8.4-apache",
        )
        self.assertEqual(latest_semver(tags, 3, ""), "5.4.7")


class TestIsMaintained(unittest.TestCase):
    def _roles(self, tmp: str, services: str | None) -> Path:
        roles_root = Path(tmp) / "roles"
        services_path = roles_root / "web-app-demo" / ROLE_FILE_META_SERVICES
        services_path.parent.mkdir(parents=True)
        if services is not None:
            services_path.write_text(services, encoding="utf-8")
        return roles_root

    def test_an_eol_role_is_not_maintained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roles_root = self._roles(tmp, "demo:\n  lifecycle: eol\n")

            self.assertFalse(is_maintained(roles_root, "web-app-demo"))

    def test_every_other_stage_is_maintained(self) -> None:
        for stage in ("pre-alpha", "beta", "maintenance", "deprecated"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tmp:
                roles_root = self._roles(tmp, f"demo:\n  lifecycle: {stage}\n")

                self.assertTrue(is_maintained(roles_root, "web-app-demo"))

    def test_a_role_without_a_lifecycle_is_maintained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roles_root = self._roles(tmp, None)

            self.assertTrue(is_maintained(roles_root, "web-app-demo"))


if __name__ == "__main__":
    unittest.main()
