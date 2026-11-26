from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from cli.meta.roles.applications.dynamic_services import (
    literally_enabled_keys,
    main,
)
from utils import PROJECT_ROOT
from utils.roles.mapping import ROLE_FILE_META_SERVICES

ROLES_DIR = PROJECT_ROOT / "roles"


def _disable_set(*args: str) -> set[str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(["--roles-dir", str(ROLES_DIR), *args])
    return {key for key in out.getvalue().strip().split(",") if key}


class TestLiterallyEnabledKeys(unittest.TestCase):
    def test_only_boolean_true_enabled_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            services = Path(tmp) / "web-app-x" / ROLE_FILE_META_SERVICES
            services.parent.mkdir(parents=True)
            services.write_text(
                "openresty:\n  enabled: true\n"
                "matomo:\n  enabled: \"{{ 'web-app-matomo' in group_names }}\"\n"
                "tor:\n  enabled: false\n"
                "lifecycle: beta\n",
                encoding="utf-8",
            )
            self.assertEqual(
                literally_enabled_keys(Path(tmp), "web-app-x"), {"openresty"}
            )

    def test_role_without_services_yields_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(literally_enabled_keys(Path(tmp), "missing"), set())


class TestRoleUnderTestKeepsItsLiteralKeys(unittest.TestCase):
    def test_openresty_is_group_conditional_somewhere(self) -> None:
        self.assertIn("openresty", _disable_set())

    def test_dashboard_keeps_its_front_proxy(self) -> None:
        self.assertNotIn("openresty", _disable_set("--role", "web-app-dashboard"))

    def test_role_keeps_every_key_it_enables_literally(self) -> None:
        literal = literally_enabled_keys(ROLES_DIR, "web-app-dashboard")
        disabled = _disable_set("--role", "web-app-dashboard", "--exclude", "asset")
        self.assertFalse(literal & disabled)
        self.assertNotIn("asset", disabled)


if __name__ == "__main__":
    unittest.main()
