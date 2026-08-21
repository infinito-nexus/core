import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.provision.project import (
    build_env_with_project_root,
    detect_project_root,
)


class TestProject(unittest.TestCase):
    def test_detect_project_root_walks_upwards(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            (root / "cli").mkdir(parents=True)
            (root / "roles").mkdir(parents=True)
            (root / "group_vars").mkdir(parents=True)

            deep_file = root / "cli" / "create" / "inventory" / "cli.py"
            deep_file.parent.mkdir(parents=True, exist_ok=True)
            deep_file.write_text("# dummy\n", encoding="utf-8")

            detected = detect_project_root(deep_file)
            self.assertEqual(detected, root)

    def test_detect_project_root_raises_if_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "somewhere" / "file.py"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x=1\n", encoding="utf-8")

            with self.assertRaises(SystemExit):
                detect_project_root(p)

    def test_build_env_with_project_root_sets_pythonpath(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()

            env = build_env_with_project_root(root)
            self.assertIn("PYTHONPATH", env)
            self.assertIn(str(root), env["PYTHONPATH"])
