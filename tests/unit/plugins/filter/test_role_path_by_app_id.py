import os
import shutil
import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleFilterError

from plugins.filter.role_path_by_app_id import (
    abs_role_path_by_application_id,
    rel_role_path_by_application_id,
)
from utils.cache.yaml import dump_yaml


def write_vars_file(base_dir, role_name, app_id):
    """
    Helper to create roles/<role_name>/vars/main.yml with application_id
    """
    role_vars_dir = str(Path(base_dir) / "roles" / role_name / "vars")
    Path(role_vars_dir).mkdir(parents=True, exist_ok=True)
    file_path = str(Path(role_vars_dir) / "main.yml")
    dump_yaml(file_path, {"application_id": app_id})
    return file_path


class TestRolePathByApplicationId(unittest.TestCase):
    def setUp(self):
        # Create temporary directory for each test and switch cwd
        self.tmp_dir = tempfile.mkdtemp()
        self.prev_cwd = str(Path.cwd())
        os.chdir(self.tmp_dir)

    def tearDown(self):
        # Restore cwd and clean up
        os.chdir(self.prev_cwd)
        shutil.rmtree(self.tmp_dir)

    def test_abs_single_match(self):
        write_vars_file(self.tmp_dir, "role_one", "app123")
        write_vars_file(self.tmp_dir, "role_two", "other_id")
        result = abs_role_path_by_application_id("app123")
        expected = str(Path(str(Path(self.tmp_dir) / "roles" / "role_one")).resolve())
        self.assertEqual(result, expected)

    def test_rel_single_match(self):
        write_vars_file(self.tmp_dir, "role_one", "app123")
        write_vars_file(self.tmp_dir, "role_two", "other_id")
        result = rel_role_path_by_application_id("app123")
        expected = os.path.relpath(
            str(Path(self.tmp_dir) / "roles" / "role_one"), self.tmp_dir
        )
        self.assertEqual(result, expected)

    def test_abs_no_match(self):
        write_vars_file(self.tmp_dir, "role_one", "app123")
        with self.assertRaises(AnsibleFilterError) as cm:
            abs_role_path_by_application_id("nonexistent")
        self.assertIn(
            "No role found with application_id='nonexistent'", str(cm.exception)
        )

    def test_rel_no_match(self):
        write_vars_file(self.tmp_dir, "role_one", "app123")
        with self.assertRaises(AnsibleFilterError) as cm:
            rel_role_path_by_application_id("nonexistent")
        self.assertIn(
            "No role found with application_id='nonexistent'", str(cm.exception)
        )

    def test_abs_multiple_match(self):
        write_vars_file(self.tmp_dir, "role_one", "dup_id")
        write_vars_file(self.tmp_dir, "role_two", "dup_id")
        with self.assertRaises(AnsibleFilterError) as cm:
            abs_role_path_by_application_id("dup_id")
        self.assertIn(
            "Multiple roles found with application_id='dup_id'", str(cm.exception)
        )

    def test_rel_multiple_match(self):
        write_vars_file(self.tmp_dir, "role_one", "dup_id")
        write_vars_file(self.tmp_dir, "role_two", "dup_id")
        with self.assertRaises(AnsibleFilterError) as cm:
            rel_role_path_by_application_id("dup_id")
        self.assertIn(
            "Multiple roles found with application_id='dup_id'", str(cm.exception)
        )


if __name__ == "__main__":
    unittest.main()
