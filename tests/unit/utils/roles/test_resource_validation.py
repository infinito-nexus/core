from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from utils.roles import resource_validation as rrv


class TestFilterRolesByMinStorage(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.roles_root = self.root / "roles"
        self.roles_root.mkdir(parents=True, exist_ok=True)

    def _write_role_config(self, role_name: str, *, yaml_text: str) -> Path:
        role_dir = self.roles_root / role_name
        (role_dir / "meta").mkdir(parents=True, exist_ok=True)
        cfg_path = role_dir / "meta" / "services.yml"
        cfg_path.write_text(yaml_text, encoding="utf-8")
        return cfg_path

    def test_keeps_role_when_min_storage_is_within_required_storage(self) -> None:
        # min_storage <= required_storage -> keep
        self._write_role_config(
            "web-app-demo",
            yaml_text="""
demo:
  min_storage: 5G
""".lstrip(),
        )

        with (
            patch.object(rrv, "_roles_root", return_value=self.roles_root),
            patch.object(rrv, "get_entity_name", return_value="demo"),
        ):
            kept = rrv.filter_roles_by_min_storage(
                role_names=["web-app-demo"],
                required_storage="10G",
                emit_warnings=False,
            )

        self.assertEqual(kept, ["web-app-demo"])

    def test_filters_out_role_when_min_storage_exceeds_required_storage(self) -> None:
        # min_storage > required_storage -> filtered out
        self._write_role_config(
            "web-app-demo",
            yaml_text="""
demo:
  min_storage: 50G
""".lstrip(),
        )

        err = io.StringIO()
        with (
            redirect_stdout(err),
            patch.object(rrv, "_roles_root", return_value=self.roles_root),
            patch.object(rrv, "get_entity_name", return_value="demo"),
        ):
            kept = rrv.filter_roles_by_min_storage(
                role_names=["web-app-demo"],
                required_storage="10G",
                emit_warnings=True,
            )

        self.assertEqual(kept, [])
        self.assertIn("requires", err.getvalue())

    def test_missing_key_treats_as_zero_and_keeps_role(self) -> None:
        # Missing min_storage -> treat as 0GB -> keep
        self._write_role_config(
            "web-app-demo",
            yaml_text="""
demo: {}
""".lstrip(),
        )

        err = io.StringIO()
        with (
            redirect_stdout(err),
            patch.object(rrv, "_roles_root", return_value=self.roles_root),
            patch.object(rrv, "get_entity_name", return_value="demo"),
        ):
            kept = rrv.filter_roles_by_min_storage(
                role_names=["web-app-demo"],
                required_storage="1G",
                emit_warnings=True,
            )

        self.assertEqual(kept, ["web-app-demo"])
        self.assertIn("Missing key services.demo.min_storage", err.getvalue())

    def test_missing_role_directory_emits_absolute_path_warning(self) -> None:
        err = io.StringIO()
        with (
            redirect_stdout(err),
            patch.object(rrv, "_roles_root", return_value=self.roles_root),
            patch.object(rrv, "get_entity_name", return_value="demo"),
        ):
            kept = rrv.filter_roles_by_min_storage(
                role_names=["web-app-does-not-exist"],
                required_storage="1G",
                emit_warnings=True,
            )

        self.assertEqual(kept, [])
        # Ensure absolute path is shown
        self.assertIn(
            str((self.roles_root / "web-app-does-not-exist").resolve()), err.getvalue()
        )

    def test_missing_services_file_skips_silently(self) -> None:
        # Role dir exists but meta/services.yml missing
        role_dir = self.roles_root / "web-app-demo"
        role_dir.mkdir(parents=True, exist_ok=True)

        err = io.StringIO()
        with (
            redirect_stdout(err),
            patch.object(rrv, "_roles_root", return_value=self.roles_root),
            patch.object(rrv, "get_entity_name", return_value="demo"),
        ):
            kept = rrv.filter_roles_by_min_storage(
                role_names=["web-app-demo"],
                required_storage="1G",
                emit_warnings=True,
            )

        self.assertEqual(kept, [])
        self.assertEqual(err.getvalue(), "")

    def test_missing_service_entry_keeps_role_without_warning(self) -> None:
        self._write_role_config(
            "web-app-demo",
            yaml_text="""
other: {}
""".lstrip(),
        )

        err = io.StringIO()
        with (
            redirect_stdout(err),
            patch.object(rrv, "_roles_root", return_value=self.roles_root),
            patch.object(rrv, "get_entity_name", return_value="demo"),
        ):
            kept = rrv.filter_roles_by_min_storage(
                role_names=["web-app-demo"],
                required_storage="1G",
                emit_warnings=True,
            )

        self.assertEqual(kept, ["web-app-demo"])
        self.assertEqual(err.getvalue(), "")

    def test_missing_primary_entity_keeps_role_without_warning(self) -> None:
        self._write_role_config(
            "web-app-demo",
            yaml_text="""
not_demo: {}
""".lstrip(),
        )

        err = io.StringIO()
        with (
            redirect_stdout(err),
            patch.object(rrv, "_roles_root", return_value=self.roles_root),
            patch.object(rrv, "get_entity_name", return_value="demo"),
        ):
            kept = rrv.filter_roles_by_min_storage(
                role_names=["web-app-demo"],
                required_storage="1G",
                emit_warnings=True,
            )

        self.assertEqual(kept, ["web-app-demo"])
        self.assertEqual(err.getvalue(), "")

    def test_invalid_yaml_emits_warning(self) -> None:
        self._write_role_config("web-app-demo", yaml_text=": this is not yaml")

        err = io.StringIO()
        with (
            redirect_stdout(err),
            patch.object(rrv, "_roles_root", return_value=self.roles_root),
            patch.object(rrv, "get_entity_name", return_value="demo"),
        ):
            kept = rrv.filter_roles_by_min_storage(
                role_names=["web-app-demo"],
                required_storage="1G",
                emit_warnings=True,
            )

        self.assertEqual(kept, [])
        self.assertIn("Failed to parse YAML:", err.getvalue())

    def test_invalid_min_storage_value_emits_warning(self) -> None:
        self._write_role_config(
            "web-app-demo",
            yaml_text="""
demo:
  min_storage: "nope"
""".lstrip(),
        )

        err = io.StringIO()
        with (
            redirect_stdout(err),
            patch.object(rrv, "_roles_root", return_value=self.roles_root),
            patch.object(rrv, "get_entity_name", return_value="demo"),
        ):
            kept = rrv.filter_roles_by_min_storage(
                role_names=["web-app-demo"],
                required_storage="10G",
                emit_warnings=True,
            )

        self.assertEqual(kept, [])
        self.assertIn("Invalid min_storage value", err.getvalue())

    def test_invalid_required_storage_raises_value_error(self) -> None:
        with patch.object(rrv, "_roles_root", return_value=self.roles_root):
            with self.assertRaises(ValueError):
                rrv.filter_roles_by_min_storage(
                    role_names=["web-app-demo"],
                    required_storage="not-a-size",
                    emit_warnings=False,
                )

    def test_entity_name_missing_emits_warning_and_skips(self) -> None:
        self._write_role_config(
            "web-app-demo",
            yaml_text="""
demo:
  min_storage: 1G
""".lstrip(),
        )

        err = io.StringIO()
        with (
            redirect_stdout(err),
            patch.object(rrv, "_roles_root", return_value=self.roles_root),
            patch.object(rrv, "get_entity_name", return_value=""),
        ):
            kept = rrv.filter_roles_by_min_storage(
                role_names=["web-app-demo"],
                required_storage="10G",
                emit_warnings=True,
            )

        self.assertEqual(kept, [])
        self.assertIn("Could not derive entity_name", err.getvalue())


if __name__ == "__main__":
    unittest.main()
