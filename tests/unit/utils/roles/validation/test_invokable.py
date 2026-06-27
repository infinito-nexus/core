# tests/unit/utils/test_invokable.py
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

import utils.roles.validation.invokable as inv
from utils.cache.yaml import dump_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN


class TestInvokable(TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="invokable_modutils_test_"))
        self.roles_dir = self.tmp / "roles"
        self.roles_dir.mkdir(parents=True, exist_ok=True)
        self.categories_file = self.roles_dir / "categories.yml"

        # This structure triggers the YAML fallback in _get_invokable_paths()
        # because it expects "categories", but we will patch _get_invokable_paths() anyway
        dump_yaml(
            self.categories_file,
            {"categories": [{"invokable_paths": ["web-app", "update", "util-desk"]}]},
        )

        def mk_role(name: str, application_id: str | None = None) -> None:
            rd = self.roles_dir / name
            (rd / "vars").mkdir(parents=True, exist_ok=True)
            if application_id is not None:
                dump_yaml(rd / ROLE_FILE_VARS_MAIN, {"application_id": application_id})
            else:
                dump_yaml(rd / ROLE_FILE_VARS_MAIN, {})

        mk_role("web-app-nextcloud", "web-app-nextcloud")
        mk_role("web-app-matomo", "matomo-app")
        mk_role("web-svc-nginx", None)  # not invokable by our patched paths
        mk_role("update", None)  # exact match
        mk_role("util-desk-custom", None)  # prefix match

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def test_list_invokable_app_ids(self) -> None:
        with (
            patch.object(inv, "PROJECT_ROOT", self.tmp),
            patch.object(
                inv,
                "_get_invokable_paths",
                return_value=["web-app", "update", "util-desk"],
            ),
        ):
            got = inv.list_invokable_app_ids()

        self.assertEqual(
            got,
            sorted(["web-app-nextcloud", "matomo-app", "update", "util-desk-custom"]),
        )

    def test_list_invokables_by_type(self) -> None:
        with (
            patch.object(inv, "PROJECT_ROOT", self.tmp),
            patch.object(
                inv,
                "_get_invokable_paths",
                return_value=["web-app", "update", "util-desk"],
            ),
        ):
            grouped = inv.list_invokables_by_type()

        # server: web-app-* minus excluded oauth2 proxy (not present in test)
        self.assertIn("server", grouped)
        self.assertIn("workstation", grouped)
        self.assertIn("universal", grouped)

        self.assertEqual(grouped["server"], sorted(["web-app-nextcloud", "matomo-app"]))
        self.assertEqual(grouped["workstation"], sorted(["util-desk-custom"]))

        # universal = invokable - (server ∪ workstation) -> update remains
        self.assertEqual(grouped["universal"], ["update"])

    def test_list_invokables_by_type_exclude(self) -> None:
        # Exercise the exclude_re path of DeploymentTypeRule via a
        # synthetic rule. The historical DEFAULT_RULES exclude (the now
        # dissolved oauth2-proxy helper role) was removed when its
        # sidecar logic was absorbed into web-app-keycloak.
        rd = self.roles_dir / "web-app-excluded"
        (rd / "vars").mkdir(parents=True, exist_ok=True)
        dump_yaml(rd / ROLE_FILE_VARS_MAIN, {})

        rules = (
            inv.DeploymentTypeRule(
                name="server",
                include_re=re.compile(r"^(web-app-|web-svc-)"),
                exclude_re=re.compile(r"^web-app-excluded$"),
            ),
            inv.DeploymentTypeRule(
                name="universal", include_re=re.compile(r".*"), exclude_re=None
            ),
        )
        with (
            patch.object(inv, "PROJECT_ROOT", self.tmp),
            patch.object(
                inv,
                "_get_invokable_paths",
                return_value=["web-app", "update", "util-desk"],
            ),
        ):
            grouped = inv.list_invokables_by_type(rules=rules)

        self.assertNotIn("web-app-excluded", grouped["server"])

    def test_list_invokables_by_type_skip_mode(self) -> None:
        def fake_skip(role_dir):
            return ["compose"] if role_dir.name == "web-app-matomo" else []

        with (
            patch.object(inv, "PROJECT_ROOT", self.tmp),
            patch.object(
                inv,
                "_get_invokable_paths",
                return_value=["web-app", "update", "util-desk"],
            ),
            patch.object(inv, "_role_skip_modes", side_effect=fake_skip),
        ):
            excluded = inv.list_invokables_by_type(skip_mode="compose")
            kept = inv.list_invokables_by_type(skip_mode="swarm")

        # web-app-matomo (app_id matomo-app) skips compose -> gone for compose,
        # present for swarm; a role without a skip list stays in both.
        self.assertNotIn("matomo-app", excluded["server"])
        self.assertIn("matomo-app", kept["server"])
        self.assertIn("web-app-nextcloud", excluded["server"])

    def test_types_from_group_names(self) -> None:
        with (
            patch.object(inv, "PROJECT_ROOT", self.tmp),
            patch.object(
                inv,
                "_get_invokable_paths",
                return_value=["web-app", "update", "util-desk"],
            ),
        ):
            got = inv.types_from_group_names(
                [
                    "all",  # not invokable -> ignored
                    "web-app-nextcloud",  # invokable + matches server rule
                    "util-desk-custom",  # invokable + matches workstation rule
                    "update",  # invokable leftover -> universal
                    "foo",  # not invokable -> ignored
                ]
            )

        self.assertEqual(got, ["server", "universal", "workstation"])


if __name__ == "__main__":
    main()
