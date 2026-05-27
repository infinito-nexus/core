"""Unit tests for ``cli.administration.inventory.validate.loaders``."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cli.administration.inventory.validate.loaders import (
    load_inventory_files,
    load_yaml_file,
)
from utils.cache.yaml import dump_yaml


class LoadersTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)


class TestLoadYamlFile(LoadersTestBase, unittest.TestCase):
    def test_plain_yaml_is_parsed(self):
        path = self.tmp_path / "plain.yml"
        dump_yaml(str(path), {"applications": {"app1": {"key": "value"}}})
        data = load_yaml_file(path)
        self.assertEqual(data, {"applications": {"app1": {"key": "value"}}})

    def test_vault_blocks_are_stripped_before_parse(self):
        path = self.tmp_path / "vaulted.yml"
        path.write_text(
            "applications:\n"
            "  app1:\n"
            "    credentials:\n"
            "      api_key: !vault |\n"
            "        $ANSIBLE_VAULT;1.1;AES256\n"
            "        61626364656667686970716e\n"
            "users:\n"
            "  alice: {}\n",
            encoding="utf-8",
        )
        data = load_yaml_file(path)
        self.assertEqual(
            data["applications"]["app1"]["credentials"]["api_key"],
            "<vaulted>",
        )
        # The next top-level section must survive the vault-stripping
        # (the regex stops at the next non-indented line).
        self.assertEqual(data["users"], {"alice": {}})

    def test_missing_file_returns_none_and_warns(self):
        data = load_yaml_file(self.tmp_path / "does-not-exist.yml")
        self.assertIsNone(data)

    def test_invalid_yaml_returns_none(self):
        path = self.tmp_path / "broken.yml"
        path.write_text("key: : : invalid\n", encoding="utf-8")
        data = load_yaml_file(path)
        self.assertIsNone(data)


class TestLoadInventoryFiles(LoadersTestBase, unittest.TestCase):
    def test_top_level_yml_with_applications_is_collected(self):
        path = self.tmp_path / "host.yml"
        dump_yaml(str(path), {"applications": {"app1": {"k": 1}}})
        result = load_inventory_files(self.tmp_path)
        self.assertIn(str(path), result)
        self.assertEqual(result[str(path)], {"app1": {"k": 1}})

    def test_yml_without_applications_is_ignored(self):
        dump_yaml(str(self.tmp_path / "noapp.yml"), {"users": {"alice": {}}})
        result = load_inventory_files(self.tmp_path)
        self.assertEqual(result, {})

    def test_recurses_into_vars_directories(self):
        host_vars = self.tmp_path / "host_vars"
        host_vars.mkdir()
        path = host_vars / "localhost.yml"
        dump_yaml(str(path), {"applications": {"app2": {"k": 2}}})
        result = load_inventory_files(self.tmp_path)
        self.assertIn(str(path), result)
        self.assertEqual(result[str(path)], {"app2": {"k": 2}})

    def test_empty_applications_block_is_skipped(self):
        dump_yaml(str(self.tmp_path / "empty.yml"), {"applications": {}})
        result = load_inventory_files(self.tmp_path)
        self.assertEqual(result, {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
