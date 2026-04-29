import os
import tempfile
import shutil
import unittest
import yaml
from plugins.lookup.application_gid import LookupModule


class TestApplicationGidLookup(unittest.TestCase):
    def setUp(self):
        # Create a temporary roles directory
        self.temp_dir = tempfile.mkdtemp()
        self.roles_dir = os.path.join(self.temp_dir, "roles")
        os.mkdir(self.roles_dir)

        # Define mock application_ids (role directory names are the canonical ids)
        self.application_ids = [
            "web-app-nextcloud",
            "web-app-moodle",
            "web-app-wordpress",
            "web-app-taiga",
        ]

        # Per req-008 an "application role" is identified by the presence of
        # at least one of the project-owned `meta/<topic>.yml` files.
        for application_id in self.application_ids:
            role_path = os.path.join(self.roles_dir, application_id, "meta")
            os.makedirs(role_path)
            with open(os.path.join(role_path, "services.yml"), "w") as f:
                yaml.dump({application_id: {"title": application_id}}, f)

        self.lookup = LookupModule()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_gid_lookup(self):
        expected_order = sorted(self.application_ids)
        for i, application_id in enumerate(expected_order):
            result = self.lookup.run([application_id], roles_dir=self.roles_dir)
            self.assertEqual(result, [10000 + i])

    def test_custom_base_gid(self):
        result = self.lookup.run(
            ["web-app-taiga"],
            roles_dir=self.roles_dir,
            base_gid=20000,
        )
        self.assertEqual(result, [20002])  # 2nd index in sorted list

    def test_application_id_not_found(self):
        with self.assertRaises(Exception) as context:
            self.lookup.run(["unknownapp"], roles_dir=self.roles_dir)
        self.assertIn("Application ID 'unknownapp' not found", str(context.exception))


if __name__ == "__main__":
    unittest.main()
