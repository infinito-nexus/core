"""Unit tests for ``cli.administration.inventory.credentials.overrides``.

There is exactly one accepted ``--set`` key shape. A short form would mean
different credentials on different apps, so it is rejected rather than guessed.
"""

from __future__ import annotations

import unittest

from cli.administration.inventory.credentials.overrides import (
    override_for,
    override_key,
    parse_overrides,
    split_override_key,
)


class TestOverrideKey(unittest.TestCase):
    def test_it_is_fully_qualified(self) -> None:
        self.assertEqual(
            override_key("web-app-x", "recaptcha.key"),
            "applications.web-app-x.secrets.credentials.recaptcha.key",
        )

    def test_it_round_trips_through_the_splitter(self) -> None:
        key = override_key("web-app-x", "recaptcha.key")
        self.assertEqual(split_override_key(key), ("web-app-x", "recaptcha.key"))


class TestParseOverrides(unittest.TestCase):
    def test_the_qualified_form_is_kept_verbatim(self) -> None:
        key = "applications.web-app-x.secrets.credentials.database_password"
        self.assertEqual(parse_overrides([f"{key}=X"]), {key: "X"})

    def test_a_value_containing_equals_survives(self) -> None:
        key = "applications.web-app-x.secrets.credentials.token"
        self.assertEqual(parse_overrides([f"{key}=a=b"]), {key: "a=b"})

    def test_every_short_form_is_rejected(self) -> None:
        for short in (
            "database_password=X",
            "credentials.database_password=X",
            "secrets.credentials.database_password=X",
            "web-app-x.secrets.credentials.database_password=X",
            "applications.web-app-x.credentials.database_password=X",
        ):
            with self.subTest(short), self.assertRaises(SystemExit):
                parse_overrides([short])


class TestOverrideFor(unittest.TestCase):
    def test_the_qualified_key_resolves(self) -> None:
        overrides = {"applications.web-app-x.secrets.credentials.key": "Z"}
        self.assertEqual(override_for("web-app-x", "key", overrides), "Z")

    def test_a_nested_key_resolves(self) -> None:
        overrides = {
            "applications.web-app-x.secrets.credentials.recaptcha.key": "Z",
        }
        self.assertEqual(override_for("web-app-x", "recaptcha.key", overrides), "Z")

    def test_another_app_does_not_resolve(self) -> None:
        overrides = {"applications.web-app-y.secrets.credentials.key": "Z"}
        self.assertIsNone(override_for("web-app-x", "key", overrides))

    def test_no_override_returns_none(self) -> None:
        self.assertIsNone(override_for("web-app-x", "key", {}))


if __name__ == "__main__":
    unittest.main()
