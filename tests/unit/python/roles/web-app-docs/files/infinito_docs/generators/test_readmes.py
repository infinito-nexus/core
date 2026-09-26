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

readmes = importlib.import_module("infinito_docs.generators.readmes")


class TestReadmes(unittest.TestCase):
    def test_every_nested_directory_gets_a_titled_readme(self) -> None:
        with TemporaryDirectory() as td:
            generated = Path(td) / "generated"
            (generated / "a").mkdir(parents=True)
            (generated / "b" / "c").mkdir(parents=True)

            readmes.create_readme_in_subdirs(generated)

            titles = {
                name: read_text(str(generated / name / "README.md")).splitlines()[0]
                for name in ("a", "b", "b/c")
            }
            self.assertFalse((generated / "README.md").exists())

        self.assertEqual(
            titles,
            {
                "a": "# Auto Generated Technical Documentation: a",
                "b": "# Auto Generated Technical Documentation: b",
                "b/c": "# Auto Generated Technical Documentation: c",
            },
        )


if __name__ == "__main__":
    unittest.main()
