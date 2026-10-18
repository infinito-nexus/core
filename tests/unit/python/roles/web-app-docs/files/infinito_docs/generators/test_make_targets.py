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

make_targets = importlib.import_module("infinito_docs.generators.make_targets")

MAKEFILE = """\
.PHONY: build
# Build the thing.
# Param domain: core | docs (empty: both)
build:
\t@echo build

.PHONY: run
# Run it.
# Usage: make run app=x
run:
\t@echo run

bare:
\t@echo bare
"""


class TestDocumentedTargets(unittest.TestCase):
    def _targets(self, text: str):
        with TemporaryDirectory() as td:
            path = Path(td) / "Makefile"
            path.write_text(text, encoding="utf-8")
            return make_targets.documented_targets(path)

    def test_every_target_is_found_in_file_order(self) -> None:
        found = [name for name, _ in self._targets(MAKEFILE)]
        self.assertEqual(found, ["build", "run", "bare"])

    def test_the_comment_block_above_a_target_is_its_documentation(self) -> None:
        doc = dict(self._targets(MAKEFILE))["build"]
        self.assertEqual(
            doc, ["Build the thing.", "Param domain: core | docs (empty: both)"]
        )

    def test_a_target_without_a_comment_carries_none(self) -> None:
        self.assertEqual(dict(self._targets(MAKEFILE))["bare"], [])

    def test_the_phony_line_is_not_mistaken_for_documentation(self) -> None:
        """``.PHONY:`` sits above the comment block and would otherwise lead it."""
        for _, doc in self._targets(MAKEFILE):
            for line in doc:
                self.assertNotIn(".PHONY", line)


class TestRenderedPage(unittest.TestCase):
    def _render(self) -> str:
        with TemporaryDirectory() as td:
            source = Path(td) / "Makefile"
            source.write_text(MAKEFILE, encoding="utf-8")
            output = Path(td) / "out" / "make_targets.rst"
            make_targets.generate(source, output)
            return read_text(str(output))

    def test_each_target_becomes_a_definition_term(self) -> None:
        page = self._render()
        self.assertIn("``make build``", page)
        self.assertIn("``make run``", page)

    def test_a_keyed_param_becomes_a_field(self) -> None:
        """The pipe is escaped; unescaped it reads as a substitution reference."""
        self.assertIn(r":param domain: core \| docs (empty: both)", self._render())

    def test_a_simple_usage_becomes_a_field(self) -> None:
        self.assertIn(":usage: make run app=x", self._render())

    def test_a_field_line_is_not_repeated_as_prose(self) -> None:
        """A field rendered twice would read as a duplicated sentence."""
        page = self._render()
        self.assertEqual(page.count(r"core \| docs (empty: both)"), 1)

    def test_an_undocumented_target_says_so(self) -> None:
        self.assertIn("Undocumented.", self._render())

    def test_a_second_asterisk_cannot_open_an_emphasis(self) -> None:
        """Two globs on one line otherwise open an emphasis that never closes."""
        with TemporaryDirectory() as td:
            source = Path(td) / "Makefile"
            source.write_text(
                "# Removes *.pyc and *.pyo files.\nx:\n\t@echo x\n", encoding="utf-8"
            )
            output = Path(td) / "out.rst"
            make_targets.generate(source, output)
            page = read_text(str(output))

        self.assertIn(r"Removes \*.pyc and \*.pyo files.", page)


if __name__ == "__main__":
    unittest.main()
