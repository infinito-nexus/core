"""Unit tests for ``cli.administration.inventory.credentials.overrides``."""

from __future__ import annotations

import unittest

from cli.administration.inventory.credentials.overrides import (
    override_for,
    parse_overrides,
)


class TestParseOverrides(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(parse_overrides([]), {})

    def test_single_pair(self):
        self.assertEqual(parse_overrides(["k=v"]), {"k": "v"})

    def test_multiple_pairs(self):
        result = parse_overrides(["a=1", "b=2"])
        self.assertEqual(result, {"a": "1", "b": "2"})

    def test_value_with_equals_is_preserved(self):
        self.assertEqual(parse_overrides(["k=a=b"]), {"k": "a=b"})

    def test_whitespace_is_stripped_around_key_and_value(self):
        self.assertEqual(parse_overrides(["  k  =  v  "]), {"k": "v"})

    def test_dotted_key_is_kept_verbatim(self):
        result = parse_overrides(["credentials.recaptcha.key=X"])
        self.assertEqual(result, {"credentials.recaptcha.key": "X"})


class TestOverrideFor(unittest.TestCase):
    def test_application_qualified_form(self):
        overrides = {"applications.web-app-x.credentials.key": "Z"}
        self.assertEqual(
            override_for("web-app-x", "key", overrides, is_primary=False),
            "Z",
        )

    def test_app_dot_credentials_form(self):
        overrides = {"web-app-x.credentials.key": "Z"}
        self.assertEqual(
            override_for("web-app-x", "key", overrides, is_primary=False),
            "Z",
        )

    def test_primary_legacy_credentials_form(self):
        overrides = {"credentials.key": "Z"}
        self.assertEqual(
            override_for("web-app-x", "key", overrides, is_primary=True),
            "Z",
        )

    def test_primary_legacy_bare_key_form(self):
        overrides = {"key": "Z"}
        self.assertEqual(
            override_for("web-app-x", "key", overrides, is_primary=True),
            "Z",
        )

    def test_legacy_forms_ignored_for_non_primary(self):
        overrides = {"credentials.key": "Z", "key": "Y"}
        self.assertIsNone(override_for("web-app-x", "key", overrides, is_primary=False))

    def test_no_match_returns_none(self):
        self.assertIsNone(override_for("web-app-x", "key", {}, is_primary=True))

    def test_dotted_nested_key_resolves_via_application_form(self):
        overrides = {
            "applications.web-app-x.credentials.recaptcha.key": "Z",
        }
        self.assertEqual(
            override_for("web-app-x", "recaptcha.key", overrides, is_primary=False),
            "Z",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
