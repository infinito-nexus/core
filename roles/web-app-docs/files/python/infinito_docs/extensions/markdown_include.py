from __future__ import annotations

from pathlib import Path

from docutils import nodes
from docutils.frontend import get_default_settings
from docutils.parsers.rst import Directive
from docutils.utils import new_document
from myst_parser.parsers.sphinx_ import MystParser


def _strip_title(doc):
    """Drop the leading title of a parsed Markdown document in place.

    Args:
        doc: docutils document produced by :class:`MystParser`.
    """
    first = doc.children[0] if doc.children else None
    if not isinstance(first, nodes.section):
        return

    if first.children and isinstance(first.children[0], nodes.title):
        if len(first.children) > 1:
            first.pop(0)
        else:
            first.children[0].clear()

    if not any(
        isinstance(child, nodes.title) and child.astext().strip()
        for child in first.children
    ):
        doc.children = list(first.children) + doc.children[1:]


class MarkdownIncludeDirective(Directive):
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = True
    has_content = False

    def _error(self, message):
        return self.state_machine.reporter.error(
            message,
            nodes.literal_block(self.block_text, self.block_text),
            line=self.lineno,
        )

    def run(self):
        env = self.state.document.settings.env
        _, filename = env.relfn2path(self.arguments[0])
        path = Path(filename)
        if not path.exists():
            return [self._error(f"File not found: {filename}")]
        try:
            markdown = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return [self._error(f"Error reading file {filename}: {exc}")]

        settings = get_default_settings(MystParser)
        settings.env = env
        doc = new_document(filename, settings=settings)
        MystParser().parse(markdown, doc)
        _strip_title(doc)
        return doc.children


def setup(app):
    app.add_directive("markdown-include", MarkdownIncludeDirective)
    return {"version": "0.1", "parallel_read_safe": True}
