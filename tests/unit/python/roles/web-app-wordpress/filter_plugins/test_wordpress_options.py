"""The WordPress options filters refuse what the generic path must not carry and
report drift per option, so a redeploy only writes what WordPress stores
differently."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


MODULE = _load_module(
    "roles/web-app-wordpress/filter_plugins/wordpress_options.py", "wordpress_options"
)

STRUCTURE = "/blog/%year%/%monthnum%/%day%/%postname%/"
OWNED = ["home", "siteurl", "blogname", "admin_email", "discourse_connect"]


def _checked(**options):
    return MODULE.wordpress_options_checked(options, OWNED)


def _drifted(desired, *, rc=0, stdout="", key="permalink_structure"):
    return MODULE.wordpress_option_drifted(
        {"rc": rc, "stdout": stdout, "item": {"key": key, "value": desired}}
    )


class TestOptionsAccepted(unittest.TestCase):
    def test_the_pinned_structure_passes_unchanged(self):
        options = {"permalink_structure": STRUCTURE}
        self.assertIs(MODULE.wordpress_options_checked(options, OWNED), options)

    def test_scalars_and_structures_pass(self):
        _checked(
            permalink_structure=STRUCTURE,
            blogdescription="Notes",
            posts_per_page=10,
            sticky_posts=[1, 2],
            activitypub_options={"actor_mode": "blog", "enabled": True},
            moderation_keys="spam",
        )


class TestOptionsRefused(unittest.TestCase):
    def _refused(self, fragment: str, **options):
        with self.assertRaises(AnsibleFilterError) as caught:
            _checked(**options)
        self.assertIn(fragment, str(caught.exception))
        return str(caught.exception)

    def test_an_option_the_role_writes_elsewhere_is_refused_by_name(self):
        message = self._refused(
            "services.wordpress.options.siteurl",
            permalink_structure=STRUCTURE,
            siteurl="https://elsewhere.example",
        )
        self.assertIn("already writes this option", message)

    def test_an_addon_option_is_refused(self):
        self._refused(
            "services.wordpress.options.discourse_connect",
            permalink_structure=STRUCTURE,
            discourse_connect={"url": "https://forum.example"},
        )

    def test_a_missing_permalink_structure_fails_instead_of_falling_back(self):
        self._refused("permalink_structure", blogdescription="Notes")

    def test_an_empty_permalink_structure_is_refused(self):
        self._refused("permalink_structure", permalink_structure="")

    def test_a_structure_without_a_tag_is_refused(self):
        self._refused("permalink_structure", permalink_structure="/blog/")

    def test_options_that_are_no_mapping_are_refused(self):
        with self.assertRaises(AnsibleFilterError):
            MODULE.wordpress_options_checked(["permalink_structure"], OWNED)

    def test_a_secret_option_name_is_refused(self):
        for name in ("mailserver_pass", "auth_key", "secure_auth_salt", "api_token"):
            with self.subTest(name=name):
                self._refused(
                    f"services.wordpress.options.{name}",
                    permalink_structure=STRUCTURE,
                    **{name: "x"},
                )

    def test_a_secret_key_nested_in_a_structure_is_refused(self):
        message = self._refused(
            "services.wordpress.options.plugin_settings",
            permalink_structure=STRUCTURE,
            plugin_settings={"providers": [{"name": "x", "openai_api_key": "y"}]},
        )
        self.assertIn("plugin_settings.providers[0].openai_api_key", message)

    def test_an_invalid_option_name_is_refused(self):
        self._refused(
            "not a WordPress option name",
            permalink_structure=STRUCTURE,
            **{"blog name; rm -rf": "x"},
        )

    def test_values_without_a_stable_stored_form_are_refused(self):
        for value in (True, False, None, 1.5):
            with self.subTest(value=value):
                self._refused(
                    "services.wordpress.options.blog_public",
                    permalink_structure=STRUCTURE,
                    blog_public=value,
                )


class TestDrift(unittest.TestCase):
    def test_a_missing_option_drifts(self):
        self.assertTrue(_drifted(STRUCTURE, rc=1))

    def test_the_old_structure_drifts_to_the_pinned_one(self):
        self.assertTrue(_drifted(STRUCTURE, stdout=json.dumps("/%postname%/")))

    def test_the_pinned_structure_as_php_prints_it_does_not_drift(self):
        php_json = '"\\/blog\\/%year%\\/%monthnum%\\/%day%\\/%postname%\\/"'
        self.assertFalse(_drifted(STRUCTURE, stdout=php_json))

    def test_an_integer_compares_with_the_string_wordpress_returns(self):
        self.assertFalse(_drifted(10, stdout='"10"'))
        self.assertTrue(_drifted(10, stdout='"20"'))

    def test_a_structure_compares_by_value(self):
        desired = {"actor_mode": "blog", "enabled": True}
        self.assertFalse(
            _drifted(desired, stdout='{"enabled":true,"actor_mode":"blog"}')
        )
        self.assertTrue(
            _drifted(desired, stdout='{"enabled":false,"actor_mode":"blog"}')
        )

    def test_a_php_warning_before_the_json_line_is_ignored(self):
        stdout = 'PHP Warning:  Undefined array key "x" in plugin.php\n"/%postname%/"'
        self.assertTrue(_drifted(STRUCTURE, stdout=stdout))
        self.assertFalse(_drifted("/%postname%/", stdout=stdout))

    def test_an_empty_mapping_matches_the_empty_array_php_prints(self):
        self.assertFalse(_drifted({}, stdout="[]"))

    def test_output_that_is_no_json_fails_and_names_the_option(self):
        with self.assertRaises(AnsibleFilterError) as caught:
            _drifted(
                STRUCTURE, stdout="PHP Notice: something", key="permalink_structure"
            )
        self.assertIn(
            "services.wordpress.options.permalink_structure", str(caught.exception)
        )


if __name__ == "__main__":
    unittest.main()
