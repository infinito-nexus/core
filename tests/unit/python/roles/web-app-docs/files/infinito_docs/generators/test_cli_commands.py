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

cli_commands = importlib.import_module("infinito_docs.generators.cli_commands")


def _command(root: Path, *parts: str, doc: str | None) -> Path:
    package = root.joinpath(*parts)
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    body = f'"""{doc}"""\n' if doc else "x = 1\n"
    main = package / "__main__.py"
    main.write_text(body, encoding="utf-8")
    return main


class TestSummary(unittest.TestCase):
    def test_the_first_docstring_line_is_the_summary(self) -> None:
        with TemporaryDirectory() as td:
            main = _command(Path(td), "pkg", doc="Does a thing.\n\nMore detail.")
            self.assertEqual(cli_commands.summary(main), "Does a thing.")

    def test_a_module_without_a_docstring_says_undocumented(self) -> None:
        with TemporaryDirectory() as td:
            main = _command(Path(td), "pkg", doc=None)
            self.assertEqual(cli_commands.summary(main), "Undocumented.")

    def test_an_unparseable_module_does_not_break_the_page(self) -> None:
        """A syntax error in one command must not lose the other 60."""
        with TemporaryDirectory() as td:
            main = Path(td) / "__main__.py"
            main.write_text("def (\n", encoding="utf-8")
            self.assertEqual(cli_commands.summary(main), "Undocumented.")

    def test_a_missing_module_does_not_break_the_page(self) -> None:
        self.assertEqual(
            cli_commands.summary(Path("/nonexistent/__main__.py")), "Undocumented."
        )


class TestRenderedPage(unittest.TestCase):
    def test_every_discovered_command_becomes_a_term(self) -> None:
        with TemporaryDirectory() as td:
            cli_dir = Path(td) / "cli"
            _command(cli_dir, "alpha", doc="First command.")
            _command(cli_dir, "beta", "gamma", doc="Nested command.")
            output = Path(td) / "out" / "cli_commands.rst"

            count = cli_commands.generate(cli_dir, output)
            page = read_text(str(output))

        self.assertEqual(count, 2)
        self.assertIn("``infinito alpha``", page)
        self.assertIn("``infinito beta gamma``", page)
        self.assertIn("Nested command.", page)


if __name__ == "__main__":
    unittest.main()
