from __future__ import annotations

import importlib
import sys
import unittest

from docutils import nodes
from docutils.frontend import get_default_settings
from docutils.parsers.rst import Parser
from docutils.utils import new_document

from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

yaml_source = importlib.import_module("infinito_docs.extensions.yaml_source")

SOURCE = "services:\n  web:\n    image: nginx\n"


def _parsed(path: str, text: str = SOURCE):
    document = new_document(path, get_default_settings(Parser))
    yaml_source.YamlParser().parse(text, document)
    return document


class TestYamlParser(unittest.TestCase):
    def test_the_file_becomes_one_literal_block(self) -> None:
        document = _parsed("/src/compose.yml")

        blocks = list(document.findall(nodes.literal_block))
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].astext(), SOURCE)
        self.assertEqual(blocks[0]["language"], "yaml")

    def test_indentation_never_reaches_the_rst_parser(self) -> None:
        document = _parsed("/src/compose.yml")

        self.assertEqual(
            len(list(document.findall(nodes.block_quote))),
            0,
            "reading yaml as reStructuredText turned every indent into a block "
            "quote, which is what produced the build's indentation errors",
        )

    def test_the_page_is_titled_after_the_file(self) -> None:
        document = _parsed(f"/src/roles/web-app-x/{ROLE_FILE_META_SERVICES}")

        titles = [node.astext() for node in document.findall(nodes.title)]
        self.assertEqual(titles, ["services.yml"])

    def test_the_page_is_marked_orphan(self) -> None:
        document = _parsed("/src/compose.yml")

        fields = [
            name.astext()
            for info in document.findall(nodes.docinfo)
            for field in info
            for name in field.findall(nodes.field_name)
        ]
        self.assertEqual(
            fields,
            ["orphan"],
            "without it every yaml page reports itself missing from the toctree",
        )

    def test_the_docinfo_comes_first_where_sphinx_reads_it(self) -> None:
        document = _parsed("/src/compose.yml")

        self.assertIsInstance(
            document[0],
            nodes.docinfo,
            "sphinx reads metadata from the first child only",
        )


if __name__ == "__main__":
    unittest.main()
