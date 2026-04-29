from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.meta.applications.in_group_deps import __main__ as mod
from utils.applications import in_group_deps as deps_mod


SERVICE_REGISTRY = {
    "matomo": {"role": "web-app-matomo"},
    "asset": {"role": "web-svc-asset"},
    "ldap": {"role": "svc-db-openldap"},
    "mariadb": {"role": "svc-db-mariadb"},
}

SAMPLE_APPS = {
    "web-svc-html": {},
    "web-svc-legal": {},
    "web-svc-file": {},
    "web-svc-asset": {},
    "web-app-matomo": {},
    "svc-db-openldap": {},
    "svc-db-mariadb": {},
}


def _meta_deps_resolver(meta_deps_map: dict[str, list[str]] | None):
    return lambda role, roles_dir: (meta_deps_map or {}).get(role, [])


class TestInGroupDepsResolver(unittest.TestCase):
    def _run_helper(
        self,
        group_names: list[str],
        *,
        applications: dict[str, object] | None = None,
        meta_deps_map: dict[str, list[str]] | None = None,
        service_registry: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return deps_mod.applications_if_group_and_all_deps(
            applications or SAMPLE_APPS,
            group_names,
            project_root="/unused",
            roles_dir="/unused",
            service_registry=service_registry or SERVICE_REGISTRY,
            meta_deps_resolver=_meta_deps_resolver(meta_deps_map),
        )

    def test_direct_group_only(self) -> None:
        result = self._run_helper(["web-svc-html"])
        self.assertIn("web-svc-html", result)
        self.assertNotIn("web-svc-legal", result)

    def test_meta_dependency_included(self) -> None:
        result = self._run_helper(
            ["web-svc-legal"],
            meta_deps_map={"web-svc-legal": ["web-svc-html"]},
        )
        self.assertIn("web-svc-legal", result)
        self.assertIn("web-svc-html", result)

    def test_service_dependency_included(self) -> None:
        apps = dict(SAMPLE_APPS)
        apps["web-svc-legal"] = {
            "services": {"matomo": {"enabled": True, "shared": True}}
        }

        result = self._run_helper(["web-svc-legal"], applications=apps)
        self.assertIn("web-svc-legal", result)
        self.assertIn("web-app-matomo", result)

    def test_direct_database_service_name_is_resolved(self) -> None:
        apps = dict(SAMPLE_APPS)
        apps["web-svc-legal"] = {
            "services": {"mariadb": {"enabled": True, "shared": True}}
        }

        result = self._run_helper(["web-svc-legal"], applications=apps)
        self.assertIn("svc-db-mariadb", result)

    def test_invalid_inputs_raise(self) -> None:
        with self.assertRaises(ValueError):
            deps_mod.applications_if_group_and_all_deps(
                "not-a-dict",
                [],
                project_root="/unused",
                roles_dir="/unused",
            )
        with self.assertRaises(ValueError):
            deps_mod.applications_if_group_and_all_deps(
                {},
                "not-a-list",
                project_root="/unused",
                roles_dir="/unused",
            )


class TestInGroupDepsCli(unittest.TestCase):
    def test_main_uses_shared_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            applications_file = Path(tmpdir) / "applications.yml"
            applications_file.write_text(
                "applications:\n  web-svc-legal: {}\n",
                encoding="utf-8",
            )

            out = io.StringIO()
            with (
                patch.object(
                    mod,
                    "find_role_dirs_by_app_id",
                    return_value=["web-svc-legal"],
                ),
                patch.object(
                    mod,
                    "applications_if_group_and_all_deps",
                    return_value={"web-svc-legal": {}},
                ) as mock_resolver,
                patch.object(
                    mod.sys,
                    "argv",
                    [
                        "prog",
                        "--applications",
                        str(applications_file),
                        "--groups",
                        "web-svc-legal",
                    ],
                ),
                patch("sys.stdout", out),
            ):
                rc = mod.main()

        self.assertEqual(rc, 0)
        self.assertIn("web-svc-legal", out.getvalue())
        self.assertEqual(
            mock_resolver.call_args.args,
            ({"web-svc-legal": {}}, ["web-svc-legal"]),
        )
        self.assertEqual(
            mock_resolver.call_args.kwargs["project_root"], mod._project_root()
        )
        self.assertEqual(
            mock_resolver.call_args.kwargs["roles_dir"],
            str(Path(mod._project_root()) / "roles"),
        )


if __name__ == "__main__":
    unittest.main()
