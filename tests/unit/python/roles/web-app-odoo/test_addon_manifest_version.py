from __future__ import annotations

import ast
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

MANIFEST = (
    PROJECT_ROOT / "roles/web-app-odoo/files/addons/auth_oauth_https/__manifest__.py"
)


def manifest_version() -> str:
    return ast.literal_eval(read_text(str(MANIFEST)))["version"]


def installable_on(series: str, version: str) -> bool:
    parts = version.split(".")
    if not 2 <= len(parts) <= 5 or not all(part.isdigit() for part in parts):
        return False
    if len(parts) <= 3 and not version.startswith(series):
        version = f"{series}.{version}"
    return version.startswith(series + ".")


class TestAddonManifestVersion(unittest.TestCase):
    def test_odoo_installs_the_addon_on_every_series(self):
        for series in ("19.0", "20.0", "21.0"):
            with self.subTest(series=series):
                self.assertTrue(
                    installable_on(series, manifest_version()),
                    f"Odoo {series} marks a module whose version names another "
                    "series as not installable and only warns about it; keep the "
                    "version in the form x.y.z so Odoo prefixes its own series",
                )

    def test_a_version_that_names_a_series_is_refused_by_the_next_one(self):
        self.assertTrue(installable_on("19.0", "19.0.1.8.0"))
        self.assertFalse(installable_on("20.0", "19.0.1.8.0"))


if __name__ == "__main__":
    unittest.main()
