from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import dump_yaml
from utils.roles.validation.deploy_id import ValidDeployId


class TestValidDeployId(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = ValidDeployId()

        self.assertTrue(
            self.validator.valid_ids,
            "Expected at least one application id discovered from repo roles/",
        )
        self.existing_app = min(self.validator.valid_ids)

        self.missing_app = "this-app-id-should-not-exist-xyz-123"

    def _write_ini_inventory(self, content: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".ini")
        os.close(fd)
        with Path(path).open("w", encoding="utf-8") as f:
            f.write(content)
        return path

    def _write_yaml_inventory(self, data) -> str:
        fd, path = tempfile.mkstemp(suffix=".yml")
        os.close(fd)
        dump_yaml(path, data)
        return path

    def test_valid_in_roles_and_ini_inventory(self) -> None:
        ini_content = f"""
[servers]
{self.existing_app},otherhost
"""
        inv = self._write_ini_inventory(ini_content)
        result = self.validator.validate(inv, [self.existing_app])
        self.assertEqual(
            result, {}, "app should be valid when in roles and ini inventory"
        )

    def test_missing_in_roles(self) -> None:
        ini_content = f"""
[servers]
{self.missing_app}
"""
        inv = self._write_ini_inventory(ini_content)
        result = self.validator.validate(inv, [self.missing_app])
        expected = {self.missing_app: {"in_roles": False, "in_inventory": True}}
        self.assertEqual(result, expected)

    def test_missing_in_inventory_ini(self) -> None:
        ini_content = """
[servers]
otherhost
"""
        inv = self._write_ini_inventory(ini_content)
        result = self.validator.validate(inv, [self.existing_app])
        expected = {self.existing_app: {"in_roles": True, "in_inventory": False}}
        self.assertEqual(result, expected)

    def test_missing_both_ini(self) -> None:
        ini_content = """
[servers]
otherhost
"""
        inv = self._write_ini_inventory(ini_content)
        result = self.validator.validate(inv, [self.missing_app])
        expected = {self.missing_app: {"in_roles": False, "in_inventory": False}}
        self.assertEqual(result, expected)

    def test_valid_in_roles_and_yaml_inventory(self) -> None:
        data = {self.existing_app: {"hosts": ["localhost"]}}
        inv = self._write_yaml_inventory(data)
        result = self.validator.validate(inv, [self.existing_app])
        self.assertEqual(result, {}, "app should be valid in roles and yaml inventory")

    def test_missing_in_roles_yaml(self) -> None:
        data = {self.missing_app: {}}
        inv = self._write_yaml_inventory(data)
        result = self.validator.validate(inv, [self.missing_app])
        expected = {self.missing_app: {"in_roles": False, "in_inventory": True}}
        self.assertEqual(result, expected)

    def test_missing_in_inventory_yaml(self) -> None:
        data = {"group": {"other": {}}}
        inv = self._write_yaml_inventory(data)
        result = self.validator.validate(inv, [self.existing_app])
        expected = {self.existing_app: {"in_roles": True, "in_inventory": False}}
        self.assertEqual(result, expected)

    def test_missing_both_yaml(self) -> None:
        data = {}
        inv = self._write_yaml_inventory(data)
        result = self.validator.validate(inv, [self.missing_app])
        expected = {self.missing_app: {"in_roles": False, "in_inventory": False}}
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
