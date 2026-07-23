"""Unit tests for `utils.roles.entity.apps.apps_for_entity`."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import _reset_cache_for_tests, dump_yaml
from utils.roles.entity.apps import apps_for_entity
from utils.roles.mapping import ROLE_FILE_VARS_MAIN


class TestAppsForEntity(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()
        self.tmp = Path(tempfile.mkdtemp(prefix="apps_for_entity_test_"))
        self.roles_dir = self.tmp / "roles"
        self.roles_dir.mkdir(parents=True, exist_ok=True)

        dump_yaml(
            self.roles_dir / "categories.yml",
            {
                "roles": {
                    "web": {
                        "app": {"title": "Applications", "invokable": True},
                        "svc": {"title": "Services", "invokable": True},
                    }
                }
            },
        )

        self._cwd = Path.cwd()
        os.chdir(self.tmp)
        self.addCleanup(lambda: os.chdir(self._cwd))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _mk_role(self, name: str, application_id: str | None) -> None:
        rd = self.roles_dir / name
        (rd / "vars").mkdir(parents=True, exist_ok=True)
        payload: dict = {}
        if application_id is not None:
            payload["application_id"] = application_id
        dump_yaml(rd / ROLE_FILE_VARS_MAIN, payload)

    def test_returns_apps_under_entity(self) -> None:
        self._mk_role("web-app-matomo", "web-app-matomo")
        self._mk_role("web-app-dashboard", "web-app-dashboard")
        self._mk_role("web-svc-cdn", "web-svc-cdn")

        self.assertEqual(
            apps_for_entity("matomo", roles_dir=self.roles_dir),
            ["web-app-matomo"],
        )
        self.assertEqual(
            apps_for_entity("cdn", roles_dir=self.roles_dir),
            ["web-svc-cdn"],
        )

    def test_falls_back_to_role_dir_name_when_application_id_missing(self) -> None:
        self._mk_role("web-app-foo", None)
        self.assertEqual(
            apps_for_entity("foo", roles_dir=self.roles_dir),
            ["web-app-foo"],
        )

    def test_unknown_entity_returns_empty(self) -> None:
        self._mk_role("web-app-matomo", "web-app-matomo")
        self.assertEqual(
            apps_for_entity("does-not-exist", roles_dir=self.roles_dir),
            [],
        )

    def test_blank_entity_returns_empty(self) -> None:
        self._mk_role("web-app-matomo", "web-app-matomo")
        self.assertEqual(apps_for_entity("", roles_dir=self.roles_dir), [])
        self.assertEqual(apps_for_entity("   ", roles_dir=self.roles_dir), [])

    def test_missing_roles_dir_returns_empty(self) -> None:
        ghost = self.tmp / "ghost-roles"
        self.assertEqual(apps_for_entity("matomo", roles_dir=ghost), [])

    def test_result_is_sorted_and_unique(self) -> None:
        self._mk_role("web-app-matomo", "web-app-matomo")
        self._mk_role("web-svc-matomo", "web-svc-matomo")

        got = apps_for_entity("matomo", roles_dir=self.roles_dir)
        self.assertEqual(got, sorted(got))
        self.assertEqual(len(got), len(set(got)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
