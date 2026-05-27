import shutil
import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleFilterError

from plugins.filter.get_role import get_role
from utils.cache.yaml import dump_yaml


class TestGetRoleFolder(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory to simulate roles structure
        self.tempdir = tempfile.mkdtemp()
        self.roles_dir = str(Path(self.tempdir) / "roles")
        Path(self.roles_dir).mkdir(parents=True)

        # Role1: matching application_id
        role1_path = str(Path(self.roles_dir) / "role1" / "vars")
        Path(role1_path).mkdir(parents=True)
        dump_yaml(str(Path(role1_path) / "main.yml"), {"application_id": "app-123"})

        # Role2: non-matching application_id
        role2_path = str(Path(self.roles_dir) / "role2" / "vars")
        Path(role2_path).mkdir(parents=True)
        dump_yaml(str(Path(role2_path) / "main.yml"), {"application_id": "app-456"})

        # Role3: missing vars directory
        Path(str(Path(self.roles_dir) / "role3")).mkdir(parents=True)

    def tearDown(self):
        # Clean up temporary directory
        shutil.rmtree(self.tempdir)

    def test_find_existing_role(self):
        # Should find role1 for application_id 'app-123'
        result = get_role("app-123", roles_path=self.roles_dir)
        self.assertEqual(result, "role1")

    def test_no_match_raises(self):
        # No role has application_id 'nonexistent'
        with self.assertRaises(AnsibleFilterError) as cm:
            get_role("nonexistent", roles_path=self.roles_dir)
        self.assertIn(
            "No role found with application_id 'nonexistent'", str(cm.exception)
        )

    def test_missing_roles_path(self):
        # Path does not exist
        invalid_path = str(Path(self.tempdir) / "invalid")
        with self.assertRaises(AnsibleFilterError) as cm:
            get_role("any", roles_path=invalid_path)
        self.assertIn(f"Roles path not found: {invalid_path}", str(cm.exception))

    def test_invalid_yaml_raises(self):
        # Create a role with invalid YAML that matches the target application_id
        bad_role_path = str(Path(self.roles_dir) / "role1" / "vars")
        with Path(str(Path(bad_role_path) / "main.yml")).open("w") as f:
            f.write("::: invalid yaml :::")  # corrupt existing main.yml

        with self.assertRaises(AnsibleFilterError) as cm:
            get_role("app-123", roles_path=self.roles_dir)
        self.assertIn("Failed to load", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
