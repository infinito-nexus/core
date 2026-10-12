import importlib.util
import unittest

from utils import PROJECT_ROOT

_spec = importlib.util.spec_from_file_location(
    "xwiki_filters",
    PROJECT_ROOT / "roles/web-app-xwiki/filter_plugins/xwiki_filters.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
xwiki_extension_status = _mod.xwiki_extension_status

EXTENSION = "org.xwiki.contrib.oidc:oidc-authenticator"


class TestExtensionStatus(unittest.TestCase):
    def test_the_pinned_version_counts_as_installed(self):
        page = f"<p>INSTALLED::{EXTENSION}::2.28.1</p>"
        self.assertEqual(xwiki_extension_status(page, "2.28.1"), 200)

    def test_another_installed_version_is_not_the_pinned_one(self):
        page = f"INSTALLED::{EXTENSION}::2.19.6"
        self.assertEqual(xwiki_extension_status(page, "2.28.1"), 404)

    def test_a_version_does_not_pass_for_one_it_only_starts_or_ends_like(self):
        self.assertEqual(
            xwiki_extension_status(f"INSTALLED::{EXTENSION}::0.10", "0.1"), 404
        )
        self.assertEqual(
            xwiki_extension_status(f"INSTALLED::{EXTENSION}::10.1", "0.1"), 404
        )

    def test_no_pin_accepts_any_installed_version(self):
        self.assertEqual(xwiki_extension_status(f"INSTALLED::{EXTENSION}::2.19.6"), 200)

    def test_a_missing_extension_is_not_installed(self):
        self.assertEqual(xwiki_extension_status(f"MISSING::{EXTENSION}", "2.28.1"), 404)


if __name__ == "__main__":
    unittest.main()
