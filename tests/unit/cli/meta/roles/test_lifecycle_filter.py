# test/unit/cli/meta/roles/test_lifecycle_filter.py
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cli.meta.roles.lifecycle_filter.__main__ import filter_roles
from utils.roles.meta_lookup import get_role_lifecycle


def _write_meta(role_dir: Path, lifecycle_value: str | None) -> None:
    """Write the role's lifecycle into meta/services.yml under the primary
    entity (per req-010). For role names without a category prefix
    (e.g. ``role-a``) the entity name equals the role name.
    """
    meta_dir = role_dir / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    role_name = role_dir.name

    if lifecycle_value is None:
        # Empty primary entry - lifecycle field absent
        content = f"{role_name}: {{}}\n"
    else:
        content = f"{role_name}:\n  lifecycle: {lifecycle_value}\n"

    (meta_dir / "services.yml").write_text(content, encoding="utf-8")


def _write_meta_stage(role_dir: Path, stage_value: str) -> None:
    meta_dir = role_dir / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    role_name = role_dir.name

    content = f"{role_name}:\n  lifecycle:\n    stage: {stage_value}\n"
    (meta_dir / "services.yml").write_text(content, encoding="utf-8")


class TestLifecycleFilter(unittest.TestCase):
    def test_extract_lifecycle_string_lowercases_and_strips(self) -> None:
        # The previous _extract_lifecycle helper was inlined into
        # utils.roles.meta_lookup.get_role_lifecycle. Round-trip through a
        # tempdir to assert the same lower/strip semantics.
        with TemporaryDirectory() as td:
            role_dir = Path(td) / "role-a"
            (role_dir / "meta").mkdir(parents=True)
            (role_dir / "meta" / "services.yml").write_text(
                'role-a:\n  lifecycle: "  StAbLe  "\n', encoding="utf-8"
            )
            self.assertEqual(get_role_lifecycle(role_dir, role_name="role-a"), "stable")

    def test_extract_lifecycle_dict_stage_supported(self) -> None:
        with TemporaryDirectory() as td:
            role_dir = Path(td) / "role-a"
            (role_dir / "meta").mkdir(parents=True)
            (role_dir / "meta" / "services.yml").write_text(
                "role-a:\n  lifecycle:\n    stage: RC\n", encoding="utf-8"
            )
            self.assertEqual(get_role_lifecycle(role_dir, role_name="role-a"), "rc")

    def test_filter_roles_whitelist_matches_only_requested_statuses(self) -> None:
        with TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()

            _write_meta(roles_dir / "role-a", "stable")
            _write_meta(roles_dir / "role-b", "beta")
            _write_meta(roles_dir / "role-c", "deprecated")
            _write_meta(roles_dir / "role-missing", None)

            result = filter_roles(
                roles_dir=roles_dir,
                mode="whitelist",
                statuses={"stable", "rc"},
                selection=None,
            )

            self.assertEqual(result, ["role-a"])

    def test_filter_roles_blacklist_includes_missing_by_default(self) -> None:
        with TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()

            _write_meta(roles_dir / "role-a", "stable")
            _write_meta(roles_dir / "role-b", "deprecated")
            _write_meta(roles_dir / "role-c", "eol")
            _write_meta(roles_dir / "role-missing", None)

            result = filter_roles(
                roles_dir=roles_dir,
                mode="blacklist",
                statuses={"deprecated", "eol"},
                selection=None,
                include_missing_lifecycle_on_blacklist=True,
            )

            self.assertEqual(result, ["role-a", "role-missing"])

    def test_filter_roles_blacklist_can_exclude_missing(self) -> None:
        with TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()

            _write_meta(roles_dir / "role-a", "stable")
            _write_meta(roles_dir / "role-b", "deprecated")
            _write_meta(roles_dir / "role-missing", None)

            result = filter_roles(
                roles_dir=roles_dir,
                mode="blacklist",
                statuses={"deprecated"},
                selection=None,
                include_missing_lifecycle_on_blacklist=False,
            )

            self.assertEqual(result, ["role-a"])

    def test_filter_roles_selection_limits_output(self) -> None:
        with TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()

            _write_meta(roles_dir / "role-a", "stable")
            _write_meta(roles_dir / "role-b", "stable")
            _write_meta(roles_dir / "role-c", "beta")

            result = filter_roles(
                roles_dir=roles_dir,
                mode="whitelist",
                statuses={"stable"},
                selection={"role-b", "role-c"},
            )

            self.assertEqual(result, ["role-b"])

    def test_filter_roles_supports_lifecycle_stage_dict(self) -> None:
        with TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()

            _write_meta_stage(roles_dir / "role-rc", "RC")
            _write_meta(roles_dir / "role-stable", "stable")

            result = filter_roles(
                roles_dir=roles_dir,
                mode="whitelist",
                statuses={"rc"},
                selection=None,
            )

            self.assertEqual(result, ["role-rc"])


if __name__ == "__main__":
    unittest.main()
