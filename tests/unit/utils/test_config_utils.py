import os
import shutil
import tempfile
import unittest

from utils.applications.config import (
    get,
    AppConfigKeyError,
    ConfigEntryNotSetError,
)


class TestGetAppConf(unittest.TestCase):
    def setUp(self):
        # Isolate working directory so that schema files can be discovered
        self._cwd = os.getcwd()
        self.tmpdir = tempfile.mkdtemp(prefix="cfgutilstest_")
        os.chdir(self.tmpdir)

        # Minimal schema structure (post req-008):
        # roles/web-app-demo/meta/schema.yml
        os.makedirs(os.path.join("roles", "web-app-demo", "meta"), exist_ok=True)
        with open(
            os.path.join("roles", "web-app-demo", "meta", "schema.yml"), "w"
        ) as f:
            f.write(
                # Defines 'features.defined_but_unset' in schema (without a value in applications),
                # plus 'features.oidc' and 'features.nested.list'
                "features:\n"
                "  oidc: {}\n"
                "  defined_but_unset: {}\n"
                "  nested:\n"
                "    list:\n"
                "      - {}\n"
            )

        # Example configuration with actual values
        self.applications = {
            "web-app-demo": {
                "features": {"oidc": True, "nested": {"list": ["first", "second"]}}
            }
        }

    def tearDown(self):
        os.chdir(self._cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # --- Tests ---

    def test_missing_app_with_skip_missing_app_returns_default_true(self):
        """If app ID is missing and skip_missing_app=True, it should return the default (True)."""
        apps = {"some-other-app": {}}
        val = get(
            apps,
            "web-app-nextcloud",
            "features.oidc",
            strict=True,
            default=True,
            skip_missing_app=True,
        )
        self.assertTrue(val)

    def test_missing_app_with_skip_missing_app_returns_default_false(self):
        """If app ID is missing and skip_missing_app=True, it should return the default (False)."""
        apps = {"svc-bkp-rmt-2-loc": {}}
        val = get(
            apps,
            "web-app-nextcloud",
            "features.oidc",
            strict=True,
            default=False,
            skip_missing_app=True,
        )
        self.assertFalse(val)

    def test_missing_app_without_skip_missing_app_and_strict_true_raises(self):
        """Missing app ID without skip_missing_app and strict=True should raise."""
        apps = {}
        with self.assertRaises(AppConfigKeyError):
            get(
                apps,
                "web-app-nextcloud",
                "features.oidc",
                strict=True,
                default=True,
                skip_missing_app=False,
            )

    def test_missing_app_without_skip_missing_app_and_strict_false_raises(self):
        apps = {}
        with self.assertRaises(AppConfigKeyError):
            get(
                apps,
                "web-app-nextcloud",
                "features.oidc",
                strict=False,
                default=True,
                skip_missing_app=False,
            )

    def test_existing_app_returns_expected_value(self):
        """Existing app and key should return the configured value."""
        val = get(
            self.applications,
            "web-app-demo",
            "features.oidc",
            strict=True,
            default=False,
            skip_missing_app=False,
        )
        self.assertTrue(val)

    def test_nested_list_index_access(self):
        """Accessing list indices should work correctly."""
        val0 = get(
            self.applications,
            "web-app-demo",
            "features.nested.list[0]",
            strict=True,
            default=None,
            skip_missing_app=False,
        )
        val1 = get(
            self.applications,
            "web-app-demo",
            "features.nested.list[1]",
            strict=True,
            default=None,
            skip_missing_app=False,
        )
        self.assertEqual(val0, "first")
        self.assertEqual(val1, "second")

    def test_schema_defined_but_unset_raises_in_strict_mode(self):
        """Schema-defined but unset value should raise in strict mode."""
        with self.assertRaises(ConfigEntryNotSetError):
            get(
                self.applications,
                "web-app-demo",
                "features.defined_but_unset",
                strict=True,
                default=False,
                skip_missing_app=False,
            )

    def test_schema_defined_but_unset_strict_false_returns_default(self):
        """Schema-defined but unset value should return default when strict=False."""
        val = get(
            self.applications,
            "web-app-demo",
            "features.defined_but_unset",
            strict=False,
            default=True,
            skip_missing_app=False,
        )
        self.assertTrue(val)

    def test_invalid_key_format_raises(self):
        """Invalid key format in path should raise AppConfigKeyError."""
        with self.assertRaises(AppConfigKeyError):
            get(
                self.applications,
                "web-app-demo",
                "features.nested.list[not-an-int]",
                strict=True,
                default=None,
                skip_missing_app=False,
            )

    def test_index_out_of_range_respects_strict(self):
        """Out-of-range index should respect strict parameter."""
        # strict=False returns default
        val = get(
            self.applications,
            "web-app-demo",
            "features.nested.list[99]",
            strict=False,
            default="fallback",
            skip_missing_app=False,
        )
        self.assertEqual(val, "fallback")
        # strict=True raises
        with self.assertRaises(AppConfigKeyError):
            get(
                self.applications,
                "web-app-demo",
                "features.nested.list[99]",
                strict=True,
                default=None,
                skip_missing_app=False,
            )


if __name__ == "__main__":
    unittest.main()
