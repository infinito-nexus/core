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

aliases = importlib.import_module("infinito_docs.generators.aliases")

ALIASES = """\
# a comment line that is not an alias
alias i8bui='m build'
alias i8far='__i8far(){ echo "$1"; }; __i8far' # does a far thing
"""


class TestParse(unittest.TestCase):
    def _parse(self, text: str):
        with TemporaryDirectory() as td:
            path = Path(td) / "aliases"
            path.write_text(text, encoding="utf-8")
            return aliases.parse(path)

    def test_only_alias_lines_are_read(self) -> None:
        self.assertEqual(
            [name for name, _, _ in self._parse(ALIASES)], ["i8bui", "i8far"]
        )

    def test_the_trailing_comment_is_captured(self) -> None:
        self.assertEqual(
            dict((n, c) for n, _, c in self._parse(ALIASES))["i8far"],
            "does a far thing",
        )

    def test_a_make_wrapper_carries_no_comment(self) -> None:
        self.assertIsNone(dict((n, c) for n, _, c in self._parse(ALIASES))["i8bui"])

    def test_an_unparseable_alias_line_raises(self) -> None:
        """Skipping it would drop the alias from the page with no trace."""
        with self.assertRaises(ValueError):
            self._parse("alias broken\n")


class TestRenderedPage(unittest.TestCase):
    def _render(self) -> str:
        with TemporaryDirectory() as td:
            source = Path(td) / "aliases"
            source.write_text(ALIASES, encoding="utf-8")
            output = Path(td) / "out" / "aliases.rst"
            aliases.generate(source, output)
            return read_text(str(output))

    def test_each_alias_becomes_a_definition_term(self) -> None:
        page = self._render()
        self.assertIn("``i8bui``", page)
        self.assertIn("``i8far``", page)

    def test_a_commented_alias_uses_its_own_description(self) -> None:
        self.assertIn("does a far thing", self._render())

    def test_a_make_wrapper_is_described_by_the_target_it_calls(self) -> None:
        self.assertIn("Runs ``make build``.", self._render())


if __name__ == "__main__":
    unittest.main()
