import re
import shutil
import tempfile
import unittest
from pathlib import Path

# Module under test
import cli.administration.inventory.validate as inventory_mod
from utils.cache.yaml import dump_yaml


class TestValidateHostKeys(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.valid_ids = {"valid-service", "another-service"}

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def write_devices_yaml(self, groups):
        # Build the YAML structure
        content = {"all": {"children": {}}}
        for group, hosts in groups.items():
            # hosts is a list of hostnames
            content["all"]["children"][group] = {"hosts": dict.fromkeys(hosts)}
        path = str(Path(self.test_dir) / "devices.yml")
        dump_yaml(path, content)
        return path

    def test_no_invalid_groups(self):
        # All groups valid
        groups = {"valid-service": ["host1"], "another-service": ["host2", "host3"]}
        self.write_devices_yaml(groups)
        errors = inventory_mod.validate_host_keys(self.valid_ids, self.test_dir)
        self.assertEqual(errors, [], f"Expected no errors, got {errors}")

    def test_single_invalid_group(self):
        # One invalid group
        groups = {"valid-service": ["host1"], "invalid-service": ["host2"]}
        self.write_devices_yaml(groups)
        errors = inventory_mod.validate_host_keys(self.valid_ids, self.test_dir)
        self.assertEqual(len(errors), 1)
        self.assertRegex(
            errors[0], r"Invalid group 'invalid-service'.*not in application_ids"
        )

    def test_multiple_invalid_groups(self):
        # Multiple invalid groups
        groups = {"bad-one": ["h1"], "bad-two": ["h2"], "valid-service": ["h3"]}
        self.write_devices_yaml(groups)
        errors = inventory_mod.validate_host_keys(self.valid_ids, self.test_dir)
        self.assertEqual(len(errors), 2)
        found = {re.search(r"Invalid group '(.+?)'", e).group(1) for e in errors}
        self.assertSetEqual(found, {"bad-one", "bad-two"})


if __name__ == "__main__":
    unittest.main()
