from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jinja2 import UndefinedError

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

from infinito_docs.identity import docs_sphinx_identity  # noqa: E402

SERVICES = """---
docs:
  sphinx:
    project: "{{ SOFTWARE_NAME }}"
    copyright: "2025, {{ INVENTOR }}"
    author: "{{ INVENTOR }}"
"""
GENERAL = """---
SOFTWARE_NAME: "Probe.Nexus"
INVENTOR: "Ada Lovelace"
"""


def _tree(root: Path, services: str, general: str) -> None:
    role = root / "roles" / "web-app-docs" / "meta"
    role.mkdir(parents=True)
    (role / "services.yml").write_text(services, encoding="utf-8")
    general_dir = root / "group_vars" / "all"
    general_dir.mkdir(parents=True)
    (general_dir / "00_general.yml").write_text(general, encoding="utf-8")


class TestDocsSphinxIdentity(unittest.TestCase):
    def test_the_configured_values_reach_the_environment_names(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _tree(root, SERVICES, GENERAL)
            self.assertEqual(
                docs_sphinx_identity(root),
                {
                    "DOCS_SPHINX_PROJECT": "Probe.Nexus",
                    "DOCS_SPHINX_COPYRIGHT": "2025, Ada Lovelace",
                    "DOCS_SPHINX_AUTHOR": "Ada Lovelace",
                },
            )

    def test_an_undefined_group_variable_is_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _tree(root, SERVICES, '---\nSOFTWARE_NAME: "Probe.Nexus"\n')
            with self.assertRaises(UndefinedError):
                docs_sphinx_identity(root)

    def test_the_repository_itself_resolves(self) -> None:
        resolved = docs_sphinx_identity(PROJECT_ROOT)
        self.assertEqual(
            set(resolved),
            {"DOCS_SPHINX_PROJECT", "DOCS_SPHINX_COPYRIGHT", "DOCS_SPHINX_AUTHOR"},
        )
        for name, value in resolved.items():
            self.assertNotIn("{{", value, name)
            self.assertTrue(value.strip(), name)


if __name__ == "__main__":
    unittest.main()
