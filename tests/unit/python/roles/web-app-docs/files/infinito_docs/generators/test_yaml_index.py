from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.cache.files import read_text

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

yaml_index = importlib.import_module("infinito_docs.generators.yaml_index")


class TestYamlIndex(unittest.TestCase):
    def test_includes_every_yaml_file_the_gitignore_keeps(self) -> None:
        with TemporaryDirectory() as td:
            source = Path(td) / "repo"
            (source / "roles" / "x").mkdir(parents=True)
            (source / "build").mkdir()
            (source / ".gitignore").write_text(
                "ignored.yml\nbuild/*\n", encoding="utf-8"
            )
            (source / "ok.yaml").write_text("a: 1\n", encoding="utf-8")
            (source / "roles" / "x" / "main.yml").write_text("b: 2\n", encoding="utf-8")
            (source / "ignored.yml").write_text("c: 3\n", encoding="utf-8")
            (source / "build" / "cache.yml").write_text("d: 4\n", encoding="utf-8")
            (source / "notes.txt").write_text("e", encoding="utf-8")
            output = Path(td) / "out" / "yaml_index.rst"

            yaml_index.generate_yaml_index(source, output)
            text = read_text(str(output))

        self.assertTrue(text.startswith(yaml_index.HEADER))
        self.assertEqual(
            [
                line
                for line in text.splitlines()
                if line.startswith(".. literalinclude::")
            ],
            [
                ".. literalinclude:: ../repo/ok.yaml",
                ".. literalinclude:: ../repo/roles/x/main.yml",
            ],
        )


if __name__ == "__main__":
    unittest.main()
