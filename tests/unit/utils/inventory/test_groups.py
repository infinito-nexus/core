"""Unit tests for utils.inventory.groups.inventory_has_group."""

from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.inventory.groups import inventory_has_group


class TestInventoryHasGroupYaml(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _write(self, name: str, body: str) -> str:
        path = self.root / name
        path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
        return str(path)

    def test_yaml_finds_nested_group(self) -> None:
        path = self._write(
            "inv.yml",
            """
            all:
              children:
                svc-swarm-node:
                  hosts:
                    swarm-mgr-01: {}
                svc-swarm-manager:
                  hosts:
                    swarm-mgr-01: {}
            """,
        )
        self.assertTrue(inventory_has_group(path, "svc-swarm-manager"))
        self.assertTrue(inventory_has_group(path, "svc-swarm-node"))

    def test_yaml_missing_group_returns_false(self) -> None:
        path = self._write(
            "inv.yml",
            """
            all:
              children:
                svc-swarm-node:
                  hosts:
                    swarm-mgr-01: {}
            """,
        )
        self.assertFalse(inventory_has_group(path, "svc-swarm-manager"))

    def test_yaml_skips_scalar_key(self) -> None:
        path = self._write(
            "inv.yml",
            """
            all:
              children:
                some-key: just-a-string
                actual-group:
                  hosts: {}
            """,
        )
        self.assertFalse(inventory_has_group(path, "some-key"))
        self.assertTrue(inventory_has_group(path, "actual-group"))


class TestInventoryHasGroupIni(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _write(self, name: str, body: str) -> str:
        path = self.root / name
        path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
        return str(path)

    def test_ini_finds_section_header(self) -> None:
        path = self._write(
            "hosts",
            """
            [svc-swarm-manager]
            mgr-01

            [web-app-mediawiki]
            mgr-01
            """,
        )
        self.assertTrue(inventory_has_group(path, "svc-swarm-manager"))
        self.assertTrue(inventory_has_group(path, "web-app-mediawiki"))

    def test_ini_finds_host_in_section(self) -> None:
        path = self._write(
            "hosts",
            """
            [grp]
            host-a, host-b host-c
            """,
        )
        self.assertTrue(inventory_has_group(path, "host-a"))
        self.assertTrue(inventory_has_group(path, "host-b"))
        self.assertTrue(inventory_has_group(path, "host-c"))

    def test_ini_skips_comments(self) -> None:
        path = self._write(
            "hosts",
            """
            # [comment-group]
            ; [also-comment]
            [real-group]
            mgr-01
            """,
        )
        self.assertFalse(inventory_has_group(path, "comment-group"))
        self.assertFalse(inventory_has_group(path, "also-comment"))
        self.assertTrue(inventory_has_group(path, "real-group"))

    def test_ini_missing_group_returns_false(self) -> None:
        path = self._write(
            "hosts",
            """
            [other]
            mgr-01
            """,
        )
        self.assertFalse(inventory_has_group(path, "missing"))


if __name__ == "__main__":
    unittest.main()
