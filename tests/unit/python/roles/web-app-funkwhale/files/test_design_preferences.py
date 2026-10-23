from __future__ import annotations

import base64
import io
import json
import os
import runpy
import sys
import unittest
from contextlib import redirect_stdout
from types import ModuleType
from unittest.mock import MagicMock, mock_open, patch

from . import PROJECT_ROOT

SCRIPT_PATH = (
    PROJECT_ROOT / "roles/web-app-funkwhale/files/python/design_preferences.py"
)

MARK = "/* mark */"
LOGO = b"\x89PNG logo"
STRINGS = {"instance__name": "Funkwhale", "ui__custom_css": MARK + "\n:root{}"}


def _file(name: str, data: bytes) -> MagicMock:
    stored = MagicMock(name="stored")
    stored.name = name
    stored.open = mock_open(read_data=data)
    return stored


class _Manager(dict):
    def __init__(self, values: dict) -> None:
        super().__init__(values)
        self.writes: list[str] = []

    def __setitem__(self, key, value) -> None:
        self.writes.append(key)
        super().__setitem__(key, value)


def _fake_modules(manager: _Manager) -> dict[str, ModuleType]:
    registries = ModuleType("dynamic_preferences.registries")
    registries.global_preferences_registry = MagicMock(
        manager=MagicMock(return_value=manager)
    )
    dynamic_preferences = ModuleType("dynamic_preferences")
    dynamic_preferences.registries = registries
    uploadedfile = ModuleType("django.core.files.uploadedfile")
    uploadedfile.SimpleUploadedFile = lambda name, data, content_type: (
        "upload",
        name,
        data,
    )
    return {
        "dynamic_preferences": dynamic_preferences,
        "dynamic_preferences.registries": registries,
        "django": ModuleType("django"),
        "django.core": ModuleType("django.core"),
        "django.core.files": ModuleType("django.core.files"),
        "django.core.files.uploadedfile": uploadedfile,
    }


class TestDesignPreferences(unittest.TestCase):
    def _run(
        self, values: dict, *, state: str = "present", logo: bytes = LOGO
    ) -> tuple[str, _Manager]:
        manager = _Manager(values)
        env = {
            "FUNKWHALE_DESIGN_STATE": state,
            "FUNKWHALE_DESIGN_MARK": MARK,
            "FUNKWHALE_DESIGN_STRINGS": json.dumps(STRINGS),
            "FUNKWHALE_DESIGN_FILES": json.dumps(
                {"ui__logo": base64.b64encode(logo).decode()}
            ),
        }
        buf = io.StringIO()
        with (
            patch.dict(os.environ, env, clear=True),
            patch.dict(sys.modules, _fake_modules(manager)),
            redirect_stdout(buf),
        ):
            runpy.run_path(str(SCRIPT_PATH), run_name="__main__")
        return buf.getvalue().strip(), manager

    def test_applies_strings_and_logo_on_an_unthemed_pod(self) -> None:
        out, manager = self._run(
            {"instance__name": "", "ui__custom_css": "", "ui__logo": None}
        )
        self.assertEqual(
            out, "FUNKWHALE_DESIGN=CHANGED instance__name,ui__custom_css,ui__logo"
        )
        self.assertEqual(manager["ui__custom_css"], STRINGS["ui__custom_css"])
        self.assertEqual(
            manager["ui__logo"], ("upload", "infinito-design-ui__logo.png", LOGO)
        )

    def test_reports_unchanged_when_everything_converged(self) -> None:
        values = dict(
            STRINGS,
            ui__logo=_file(
                "dynamic_preferences/ui__logo/infinito-design-ui__logo.png", LOGO
            ),
        )
        out, manager = self._run(values)
        self.assertEqual(out, "FUNKWHALE_DESIGN=UNCHANGED")
        self.assertEqual(manager.writes, [])

    def test_leaves_a_pod_with_foreign_custom_css_alone(self) -> None:
        out, manager = self._run(
            {
                "instance__name": "Mine",
                "ui__custom_css": "body{color:red}",
                "ui__logo": None,
            }
        )
        self.assertEqual(out, "FUNKWHALE_DESIGN=FOREIGN")
        self.assertEqual(manager.writes, [])

    def test_absent_state_removes_only_what_the_role_wrote(self) -> None:
        own_logo = _file(
            "dynamic_preferences/ui__logo/infinito-design-ui__logo.png", LOGO
        )
        out, manager = self._run(
            dict(STRINGS, ui__logo=own_logo), state="absent", logo=b""
        )
        self.assertEqual(
            out, "FUNKWHALE_DESIGN=CHANGED instance__name,ui__custom_css,ui__logo"
        )
        self.assertEqual(manager["ui__custom_css"], "")
        self.assertIsNone(manager["ui__logo"])

    def test_absent_state_keeps_settings_an_admin_chose(self) -> None:
        admin_logo = _file("dynamic_preferences/ui__logo/mine.png", LOGO)
        out, manager = self._run(
            {"instance__name": "Mine", "ui__custom_css": "", "ui__logo": admin_logo},
            state="absent",
            logo=b"",
        )
        self.assertEqual(out, "FUNKWHALE_DESIGN=UNCHANGED")
        self.assertEqual(manager.writes, [])


if __name__ == "__main__":
    unittest.main()
