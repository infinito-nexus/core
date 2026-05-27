from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.meta.roles.applications.resolution.combined.errors import (
    CombinedResolutionError,
)
from cli.meta.roles.applications.resolution.combined.yaml_utils import load_yaml_file


class TestCombinedYamlUtils(unittest.TestCase):
    def test_load_yaml_file_ok(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.yml"
            p.write_text("a: 1\nb:\n  c: test\n", encoding="utf-8")
            data = load_yaml_file(p)
            self.assertEqual(data["a"], 1)
            self.assertEqual(data["b"]["c"], "test")

    def test_load_yaml_file_invalid_yaml_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.yml"
            p.write_text("a: [1, 2\n", encoding="utf-8")  # missing closing bracket
            with self.assertRaises(CombinedResolutionError):
                load_yaml_file(p)


if __name__ == "__main__":
    unittest.main()
