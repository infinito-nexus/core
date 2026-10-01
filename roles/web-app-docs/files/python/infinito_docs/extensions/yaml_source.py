"""Render a YAML source file as the literal block it is.

Sphinx read ``.yml`` and ``.yaml`` through the reStructuredText parser, where
YAML indentation reads as a block quote: 9650 of the build's ``Unexpected
indentation`` errors came from that one mapping, and the pages carried no title
either, because a YAML file has no heading to find.
"""

from __future__ import annotations

from pathlib import Path

from docutils import nodes
from sphinx.parsers import Parser


def _orphan() -> nodes.docinfo:
    """Return the docinfo Sphinx reads the ``orphan`` metadata flag from."""
    field = nodes.field()
    field += nodes.field_name(text="orphan")
    field += nodes.field_body()
    info = nodes.docinfo()
    info += field
    return info


class YamlParser(Parser):
    """Parse a YAML file into a page titled after it, holding its source."""

    supported = ("yaml",)

    def parse(self, inputstring: str, document: nodes.document) -> None:
        """Fill ``document`` with the source of the YAML file it was read from.

        The page is marked ``orphan``: a YAML file is reference material reached
        from a link in prose, not a chapter of the manual, and every one of them
        would otherwise report itself missing from the toctree.

        Args:
            inputstring: the file's content.
            document: the docutils document to populate.
        """
        title = Path(str(document["source"])).name
        document += _orphan()
        section = nodes.section(ids=[nodes.make_id(title)], names=[title])
        section += nodes.title(text=title)
        section += nodes.literal_block(inputstring, inputstring, language="yaml")
        document += section


def setup(app):
    app.add_source_parser(YamlParser)
    return {"version": "1.0", "parallel_read_safe": True}
