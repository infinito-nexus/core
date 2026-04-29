"""Unit tests for utils.roles.meta_lookup (req-010 AC).

Covers:
  * service role with run_after / lifecycle on its primary entity;
  * multi-entity role where the primary entity is a metadata-only holder;
  * absent run_after (returns []);
  * absent lifecycle (returns None);
  * malformed meta/services.yml (raises a clear error).
"""

from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.roles.meta_lookup import (
    MetaServicesShapeError,
    get_role_lifecycle,
    get_role_run_after,
)


class _RoleFixtures:
    def __init__(self, root: Path):
        self.root = root

    def write(self, role_name: str, body: str) -> Path:
        role_dir = self.root / role_name
        (role_dir / "meta").mkdir(parents=True, exist_ok=True)
        path = role_dir / "meta" / "services.yml"
        path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
        return role_dir


class TestMetaLookup(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fx = _RoleFixtures(Path(self.tmp.name))

    def test_service_role_with_run_after_and_lifecycle(self) -> None:
        role_dir = self.fx.write(
            "web-app-gitea",
            """
            gitea:
              image: gitea/gitea
              run_after:
                - svc-db-postgres
                - web-app-keycloak
              lifecycle: stable
            """,
        )

        self.assertEqual(
            get_role_run_after(role_dir, role_name="web-app-gitea"),
            ["svc-db-postgres", "web-app-keycloak"],
        )
        self.assertEqual(
            get_role_lifecycle(role_dir, role_name="web-app-gitea"),
            "stable",
        )

    def test_multi_entity_metadata_only_primary_holder(self) -> None:
        role_dir = self.fx.write(
            "web-app-bluesky",
            """
            bluesky:
              run_after:
                - web-app-keycloak
              lifecycle: alpha
            api:
              ports:
                local:
                  http: 8030
            web:
              ports:
                local:
                  http: 8031
            """,
        )

        self.assertEqual(
            get_role_run_after(role_dir, role_name="web-app-bluesky"),
            ["web-app-keycloak"],
        )
        self.assertEqual(
            get_role_lifecycle(role_dir, role_name="web-app-bluesky"),
            "alpha",
        )

    def test_returns_empty_list_when_run_after_absent(self) -> None:
        role_dir = self.fx.write(
            "web-app-yourls",
            """
            yourls:
              lifecycle: beta
            """,
        )
        self.assertEqual(
            get_role_run_after(role_dir, role_name="web-app-yourls"),
            [],
        )

    def test_returns_none_when_lifecycle_absent(self) -> None:
        role_dir = self.fx.write(
            "web-app-yourls",
            """
            yourls:
              run_after:
                - svc-db-postgres
            """,
        )
        self.assertIsNone(get_role_lifecycle(role_dir, role_name="web-app-yourls"))

    def test_returns_empty_when_services_file_missing(self) -> None:
        role_dir = self.fx.root / "desk-something"
        role_dir.mkdir(parents=True)
        self.assertEqual(
            get_role_run_after(role_dir, role_name="desk-something"),
            [],
        )
        self.assertIsNone(get_role_lifecycle(role_dir, role_name="desk-something"))

    def test_malformed_yaml_raises_clear_error(self) -> None:
        role_dir = self.fx.root / "web-app-broken"
        (role_dir / "meta").mkdir(parents=True)
        (role_dir / "meta" / "services.yml").write_text(
            "key: value\n:foo: ]invalid[\n  - not\n", encoding="utf-8"
        )
        with self.assertRaises(MetaServicesShapeError):
            get_role_run_after(role_dir, role_name="web-app-broken")

    def test_non_dict_root_raises_clear_error(self) -> None:
        role_dir = self.fx.root / "web-app-listroot"
        (role_dir / "meta").mkdir(parents=True)
        (role_dir / "meta" / "services.yml").write_text(
            "- this\n- is\n- a list\n", encoding="utf-8"
        )
        with self.assertRaises(MetaServicesShapeError):
            get_role_lifecycle(role_dir, role_name="web-app-listroot")


if __name__ == "__main__":
    unittest.main()
