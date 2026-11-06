from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from docutils import nodes
from docutils.utils import new_document

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

markdown_include = importlib.import_module("infinito_docs.extensions.markdown_include")


class _Reporter:
    def error(self, message, *args, **kwargs):
        return ("ERROR", message)


class _Env:
    def __init__(self, base: Path) -> None:
        self._base = base

    def relfn2path(self, name):
        return name, str(self._base / name)


class _App:
    def __init__(self) -> None:
        self.added = {}

    def add_directive(self, name, directive) -> None:
        self.added[name] = directive


def _section(*children):
    section = nodes.section()
    section += list(children)
    doc = new_document("page.md")
    doc += section
    return doc


class TestMarkdownInclude(unittest.TestCase):
    def test_setup_registers_the_directive(self) -> None:
        app = _App()
        markdown_include.setup(app)
        self.assertIs(
            app.added["markdown-include"], markdown_include.MarkdownIncludeDirective
        )

    def test_missing_file_reports_an_error(self) -> None:
        with TemporaryDirectory() as td:
            directive = markdown_include.MarkdownIncludeDirective(
                name="markdown-include",
                arguments=["nope.md"],
                options={},
                content=[],
                lineno=1,
                content_offset=0,
                block_text=".. markdown-include:: nope.md",
                state=SimpleNamespace(
                    document=SimpleNamespace(
                        settings=SimpleNamespace(env=_Env(Path(td)))
                    )
                ),
                state_machine=SimpleNamespace(reporter=_Reporter()),
            )

            (result,) = directive.run()

        self.assertEqual(result[0], "ERROR")
        self.assertIn("File not found", result[1])

    def test_title_is_dropped_and_its_section_unwrapped(self) -> None:
        paragraph = nodes.paragraph(text="Body")
        doc = _section(nodes.title(text="README"), paragraph)

        markdown_include._strip_title(doc)

        self.assertEqual(doc.children, [paragraph])

    def test_lone_title_is_emptied_and_unwrapped(self) -> None:
        title = nodes.title(text="README")
        doc = _section(title)

        markdown_include._strip_title(doc)

        self.assertEqual(doc.children, [title])
        self.assertEqual(title.astext(), "")


if __name__ == "__main__":
    unittest.main()
