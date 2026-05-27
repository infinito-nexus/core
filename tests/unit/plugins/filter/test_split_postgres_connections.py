import importlib.util
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import ModuleType

from ansible.errors import AnsibleFilterError


def load_filter_module(repo_root: str) -> ModuleType:
    """
    Load the filter plugin from:
      plugins/filter/split_postgres_connections.py
    """
    plugin_path = str(
        Path(repo_root) / "plugins" / "filter" / "split_postgres_connections.py"
    )
    if not Path(plugin_path).is_file():
        raise FileNotFoundError(f"Filter plugin not found at {plugin_path}")
    spec = importlib.util.spec_from_file_location(
        "split_postgres_connections_plugin", plugin_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def write_role_vars(repo_root: str, role_name: str, database_type: str | None):
    """
    Create a minimal role with optional vars/main.yml containing database_type.
    """
    role_dir = str(Path(repo_root) / "roles" / role_name)
    vars_dir = str(Path(role_dir) / "vars")
    Path(role_dir).mkdir(parents=True, exist_ok=True)
    if database_type is not None:
        Path(vars_dir).mkdir(parents=True, exist_ok=True)
        with Path(str(Path(vars_dir) / "main.yml")).open("w", encoding="utf-8") as f:
            f.write(
                textwrap.dedent(f"""\
                # auto-generated for test
                database_type: {database_type}
            """)
            )


class SplitPostgresConnectionsTests(unittest.TestCase):
    def setUp(self):
        # Create an isolated temporary repository layout
        self.repo = tempfile.mkdtemp(prefix="repo_")
        self.roles_dir = str(Path(self.repo) / "roles")
        Path(self.roles_dir).mkdir(parents=True, exist_ok=True)

        # Create roles:
        # - app_a (postgres)
        # - app_b (postgres)
        # - app_c (mysql)
        # - app_d (no vars/main.yml)
        write_role_vars(self.repo, "app_a", "postgres")
        write_role_vars(self.repo, "app_b", "postgres")
        write_role_vars(self.repo, "app_c", "mysql")
        write_role_vars(self.repo, "app_d", None)

        # Copy the real plugin into this temp repo structure, preserving the
        # project layout (plugins/filter/).
        src_plugin_path = str(
            Path(str(Path.cwd()))
            / "plugins"
            / "filter"
            / "split_postgres_connections.py"
        )
        if not Path(src_plugin_path).is_file():
            self.skipTest(f"Source plugin not found at {src_plugin_path}")
        dst_plugin_dir = str(Path(self.repo) / "plugins" / "filter")
        Path(dst_plugin_dir).mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            src_plugin_path,
            str(Path(dst_plugin_dir) / "split_postgres_connections.py"),
        )

        self.mod = load_filter_module(self.repo)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_registry_contains_filters(self):
        registry = self.mod.FilterModule().filters()
        self.assertIn("split_postgres_connections", registry)

    def test_split_postgres_connections_division(self):
        # There are 2 postgres roles -> 200 / 2 = 100
        avg = self.mod.split_postgres_connections(200, roles_dir=self.roles_dir)
        self.assertEqual(avg, 100)

        # 5 / 2 -> floor 2
        self.assertEqual(
            self.mod.split_postgres_connections(5, roles_dir=self.roles_dir), 2
        )

        # Safety floor: at least 1
        self.assertEqual(
            self.mod.split_postgres_connections(1, roles_dir=self.roles_dir), 1
        )

    def test_split_handles_non_int_input(self):
        with self.assertRaises(AnsibleFilterError):
            self.mod.split_postgres_connections("not-an-int", roles_dir=self.roles_dir)

    def test_missing_roles_dir_raises(self):
        # Current plugin behavior: raise if roles_dir does not exist
        with self.assertRaises(AnsibleFilterError):
            self.mod.split_postgres_connections(100, roles_dir="/does/not/exist")


if __name__ == "__main__":
    unittest.main()
