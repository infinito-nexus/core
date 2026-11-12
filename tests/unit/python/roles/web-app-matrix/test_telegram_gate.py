"""The telegram bridge gate of web-app-matrix.

mautrix-telegram needs an API id and hash to register, so a deployment
without them must not be handed the bridge. The gate used to be a compose
task filtering the bridge list, which left the ansible flavor configuring a
bridge it could not authenticate; it now sits on ``MATRIX_BRIDGE_ADDONS``,
which both flavors read. The compose list has to stay derived from that
variable, or deleting the task takes the filter with it.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import ClassVar

from jinja2 import Environment, StrictUndefined

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = "web-app-matrix"
ROLE_DIR = Path(PROJECT_ROOT) / "roles" / ROLE
VARS = ROLE_DIR / ROLE_FILE_VARS_MAIN
COMPOSE_MAIN = ROLE_DIR / "tasks" / "flavor" / "compose" / "main.yml"

DECLARED = [
    {"value": {"enabled": True, "config": {"bridge_name": "telegram"}}},
    {"value": {"enabled": True, "config": {"bridge_name": "signal"}}},
]


def _ansible_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"y", "yes", "true", "on", "1"}
    return bool(value)


class TestTelegramGate(unittest.TestCase):
    variables: ClassVar[dict] = load_yaml(str(VARS))

    def _render(self, key: str, **context) -> str:
        """Render one role variable.

        Args:
            key: the variable name in ``vars/main.yml``.
            context: values the expression reads, plus ``credentials`` for
                what ``lookup('config', ...)`` answers.
        """
        credentials = context.pop("credentials", "")
        env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - renders an ansible var expression, not markup
        env.filters["bool"] = _ansible_bool
        env.globals["lookup"] = lambda *_a, **_kw: credentials
        return env.from_string(self.variables[key]).render(
            application_id=ROLE, **context
        )

    def test_both_credentials_make_telegram_usable(self) -> None:
        rendered = self._render("MATRIX_TELEGRAM_USABLE", credentials="set")

        self.assertTrue(_ansible_bool(rendered))

    def test_a_blank_credential_makes_telegram_unusable(self) -> None:
        for blank in ("", "   "):
            with self.subTest(blank=repr(blank)):
                rendered = self._render("MATRIX_TELEGRAM_USABLE", credentials=blank)

                self.assertFalse(_ansible_bool(rendered))

    def test_an_unusable_telegram_is_dropped_from_the_addons(self) -> None:
        rendered = self._render(
            "MATRIX_BRIDGE_ADDONS",
            MATRIX_BRIDGE_ADDONS_DECLARED=DECLARED,
            MATRIX_TELEGRAM_USABLE=False,
        )

        self.assertNotIn("telegram", rendered)
        self.assertIn("signal", rendered)

    def test_a_usable_telegram_stays_in_the_addons(self) -> None:
        rendered = self._render(
            "MATRIX_BRIDGE_ADDONS",
            MATRIX_BRIDGE_ADDONS_DECLARED=DECLARED,
            MATRIX_TELEGRAM_USABLE=True,
        )

        self.assertIn("telegram", rendered)
        self.assertIn("signal", rendered)

    def test_the_compose_list_is_derived_from_the_gated_addons(self) -> None:
        build = load_yaml_any(str(COMPOSE_MAIN))[0]["set_fact"]["MATRIX_BRIDGES"]

        self.assertIn(
            "MATRIX_BRIDGE_ADDONS",
            build,
            "a compose list read straight from addons bypasses the gate",
        )


if __name__ == "__main__":
    unittest.main()
