import tempfile
import unittest
from pathlib import Path

from plugins.filter.get.all.application_ids import get_all_application_ids
from utils.cache.yaml import dump_yaml


class TestGetAllApplicationIds(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.roles_dir = str(Path(self.tmpdir.name) / "roles")
        Path(self.roles_dir).mkdir(parents=True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def create_role(self, role_name, data):
        path = str(Path(self.roles_dir) / role_name / "vars")
        Path(path).mkdir(parents=True, exist_ok=True)
        dump_yaml(str(Path(path) / "main.yml"), data)

    def test_single_application_id(self):
        self.create_role("role1", {"application_id": "app1"})
        result = get_all_application_ids(self.roles_dir)
        self.assertEqual(result, ["app1"])

    def test_multiple_application_ids(self):
        self.create_role("role1", {"application_id": "app1"})
        self.create_role("role2", {"application_id": "app2"})
        result = get_all_application_ids(self.roles_dir)
        self.assertEqual(sorted(result), ["app1", "app2"])

    def test_duplicate_application_ids(self):
        self.create_role("role1", {"application_id": "app1"})
        self.create_role("role2", {"application_id": "app1"})
        result = get_all_application_ids(self.roles_dir)
        self.assertEqual(result, ["app1"])

    def test_missing_application_id(self):
        self.create_role("role1", {"other_key": "value"})
        result = get_all_application_ids(self.roles_dir)
        self.assertEqual(result, [])

    def test_no_roles_directory(self):
        empty_dir = str(Path(self.tmpdir.name) / "no_roles_here")
        result = get_all_application_ids(empty_dir)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
