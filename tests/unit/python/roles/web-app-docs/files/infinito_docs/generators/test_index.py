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

index = importlib.import_module("infinito_docs.generators.index")


class TestIndex(unittest.TestCase):
    def test_toctree_lists_every_page_relative_to_the_index(self) -> None:
        with TemporaryDirectory() as td:
            pages = Path(td) / "generated" / "roles"
            pages.mkdir(parents=True)
            (pages / "b.rst").write_text("b", encoding="utf-8")
            (pages / "a.rst").write_text("a", encoding="utf-8")
            (pages / "README.md").write_text("# skip", encoding="utf-8")
            output = Path(td) / "roles" / "ansible_role_glosar.rst"

            index.generate_ansible_roles_index(pages, output, "Ansible Role Glossary")
            text = read_text(str(output))

        self.assertEqual(
            text,
            "Ansible Role Glossary\n=====================\n\n"
            ".. toctree::\n   :maxdepth: 1\n   :caption: Ansible Role Glossary\n\n"
            "   ../generated/roles/a\n   ../generated/roles/b\n",
        )

    def test_missing_pages_directory_writes_nothing(self) -> None:
        with TemporaryDirectory() as td:
            output = Path(td) / "index.rst"

            index.generate_ansible_roles_index(Path(td) / "absent", output, "Caption")

            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
