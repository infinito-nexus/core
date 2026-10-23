from __future__ import annotations

import importlib.util
import sys
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT

VERSION_PHP_31 = """<?php
$OC_Version = array(31,0,11,1);
$OC_VersionString = '31.0.11';
$OC_Edition = '';
$OC_Channel = 'stable';
$OC_VersionCanBeUpgradedFrom = array (
  'nextcloud' =>
  array (
    '30.0' => true,
    '31.0' => true,
  ),
);
$OC_Build = '2025-11-13T12:00:00+00:00 0123456789abcdef';
$vendor = 'nextcloud';
"""

ENTRYPOINT_UPGRADE_OUTPUT = """Initializing nextcloud 32.0.1.2 ...
Upgrading nextcloud from 31.0.11.1 ...
Setting log level to debugging
Updating database schema
Updated database
Disabled incompatible app: whiteboard
Update app deck from App Store
Starting code integrity check...
Finished code integrity check
Update successful
Maintenance mode is kept active
Resetting log level
The following apps have been disabled:
 deck
 whiteboard
Initializing finished
"""

APP_LIST_JSON = (
    '{"enabled":{"activity":"5.0.0","deck":"1.16.2","files":"2.4.0"},'
    '"disabled":{"whiteboard":"1.0.5"}}'
)

STATUS_JSON = (
    '{"installed":true,"version":"32.0.1.2","versionstring":"32.0.1",'
    '"edition":"","maintenance":false,"needsDbUpgrade":false,'
    '"productname":"Nextcloud","extendedSupport":false}'
)


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


MODULE = _load_module(
    "roles/web-app-nextcloud/filter_plugins/nextcloud_upgrade.py", "nextcloud_upgrade"
)


class TestNextcloudVersionPhp(unittest.TestCase):
    def test_array_form_yields_the_dotted_version(self):
        self.assertEqual(MODULE.nextcloud_version_php(VERSION_PHP_31), "31.0.11.1")

    def test_short_array_form_yields_the_dotted_version(self):
        content = "<?php\n$OC_Version = [ 34, 0, 5, 1 ];\n"
        self.assertEqual(MODULE.nextcloud_version_php(content), "34.0.5.1")

    def test_version_string_is_not_mistaken_for_the_version_array(self):
        content = "<?php\n$OC_VersionString = '31.0.11';\n"
        with self.assertRaises(AnsibleFilterError):
            MODULE.nextcloud_version_php(content)

    def test_non_numeric_component_is_rejected(self):
        content = "<?php\n$OC_Version = array(31,0,'x',1);\n"
        with self.assertRaises(AnsibleFilterError):
            MODULE.nextcloud_version_php(content)

    def test_empty_content_is_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            MODULE.nextcloud_version_php("")


class TestNextcloudTagMajor(unittest.TestCase):
    def test_floating_major_tag(self):
        self.assertEqual(MODULE.nextcloud_tag_major("34-fpm-alpine"), 34)

    def test_full_version_tag(self):
        self.assertEqual(MODULE.nextcloud_tag_major("32.0.3-fpm-alpine"), 32)

    def test_dotted_version_string(self):
        self.assertEqual(MODULE.nextcloud_tag_major("31.0.11.1"), 31)

    def test_named_channel_tag_is_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            MODULE.nextcloud_tag_major("production-fpm-alpine")


class TestNextcloudMajorSteps(unittest.TestCase):
    def test_no_installation_needs_no_step(self):
        self.assertEqual(MODULE.nextcloud_major_steps("", "34-fpm-alpine"), [])

    def test_same_major_needs_no_step(self):
        self.assertEqual(MODULE.nextcloud_major_steps("34.0.4.1", "34-fpm-alpine"), [])

    def test_one_major_below_steps_to_the_pinned_tag(self):
        self.assertEqual(
            MODULE.nextcloud_major_steps("33.0.2.1", "34-fpm-alpine"),
            ["34-fpm-alpine"],
        )

    def test_three_majors_below_step_through_every_major(self):
        self.assertEqual(
            MODULE.nextcloud_major_steps("31.0.11.1", "34-fpm-alpine"),
            ["32-fpm-alpine", "33-fpm-alpine", "34-fpm-alpine"],
        )

    def test_intermediate_tags_keep_the_pinned_variant_suffix(self):
        self.assertEqual(
            MODULE.nextcloud_major_steps("31.0.12.2", "33.0.1-apache"),
            ["32-apache", "33.0.1-apache"],
        )

    def test_pin_of_the_first_intermediate_major_is_one_step(self):
        self.assertEqual(
            MODULE.nextcloud_major_steps("31.0.12.2", "32-fpm-alpine"),
            ["32-fpm-alpine"],
        )

    def test_newer_data_than_the_pin_is_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            MODULE.nextcloud_major_steps("35.0.0.1", "34-fpm-alpine")

    def test_named_channel_pin_is_rejected_for_existing_data(self):
        with self.assertRaises(AnsibleFilterError):
            MODULE.nextcloud_major_steps("31.0.11.1", "production-fpm-alpine")


class TestNextcloudDisabledApps(unittest.TestCase):
    def test_an_incompatible_app_that_stayed_off_is_disabled(self):
        self.assertEqual(
            MODULE.nextcloud_disabled_apps(ENTRYPOINT_UPGRADE_OUTPUT, APP_LIST_JSON),
            ["whiteboard"],
        )

    def test_an_app_the_app_store_updated_and_enabled_again_is_not_disabled(self):
        output = (
            "Disabled incompatible app: deck\n"
            "Update app deck from App Store\n"
            "Update successful\n"
        )
        self.assertEqual(MODULE.nextcloud_disabled_apps(output, APP_LIST_JSON), [])

    def test_an_app_the_entrypoint_lists_after_an_update_is_not_disabled(self):
        self.assertNotIn(
            "deck",
            MODULE.nextcloud_disabled_apps(ENTRYPOINT_UPGRADE_OUTPUT, APP_LIST_JSON),
        )

    def test_repeated_lines_are_reported_once(self):
        output = (
            "Disabled incompatible app: news\n"
            "Disabled incompatible app: bbb\n"
            "Disabled incompatible app: news\n"
        )
        self.assertEqual(
            MODULE.nextcloud_disabled_apps(output, APP_LIST_JSON), ["bbb", "news"]
        )

    def test_an_empty_enabled_list_keeps_every_disabled_app(self):
        output = "Disabled incompatible app: news\n"
        app_list = '{"enabled":[],"disabled":{"news":"25.0.0"}}'
        self.assertEqual(MODULE.nextcloud_disabled_apps(output, app_list), ["news"])

    def test_output_without_upgrade_yields_nothing(self):
        self.assertEqual(MODULE.nextcloud_disabled_apps("", APP_LIST_JSON), [])

    def test_app_list_without_json_is_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            MODULE.nextcloud_disabled_apps(ENTRYPOINT_UPGRADE_OUTPUT, "maintenance")


class TestNextcloudStatus(unittest.TestCase):
    def test_plain_json_is_parsed(self):
        status = MODULE.nextcloud_status(STATUS_JSON)
        self.assertEqual(status["versionstring"], "32.0.1")
        self.assertFalse(status["maintenance"])

    def test_php_notices_before_the_json_are_skipped(self):
        output = "PHP Deprecated:  something in /var/www/html/lib/x.php\n" + STATUS_JSON
        self.assertTrue(MODULE.nextcloud_status(output)["installed"])

    def test_json_without_status_keys_is_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            MODULE.nextcloud_status('{"installed":true}')

    def test_output_without_json_is_rejected(self):
        with self.assertRaises(AnsibleFilterError):
            MODULE.nextcloud_status("Nextcloud is not installed")


if __name__ == "__main__":
    unittest.main()
