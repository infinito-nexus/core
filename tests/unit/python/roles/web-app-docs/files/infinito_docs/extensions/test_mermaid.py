from __future__ import annotations

import importlib
import sys
import unittest
from unittest import mock

from docutils import nodes
from docutils.frontend import get_default_settings
from docutils.parsers.rst import Parser
from docutils.utils import new_document

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

mermaid = importlib.import_module("infinito_docs.extensions.mermaid")


def _transform(*blocks: nodes.literal_block):
    document = new_document("<test>", get_default_settings(Parser))
    for block in blocks:
        document.append(block)
    mermaid.MermaidFences(document).run()
    return document


class TestMermaidFences(unittest.TestCase):
    def test_a_mermaid_block_becomes_a_raw_diagram(self) -> None:
        source = 'flowchart LR\n    a["a"] --> b["b"]'
        document = _transform(
            nodes.literal_block(source, source, language=mermaid.LANGUAGE)
        )

        raw = list(document.findall(nodes.raw))
        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0].get("format"), "html")
        self.assertTrue(raw[0].astext().startswith('<pre class="mermaid">'))
        self.assertEqual(len(list(document.findall(nodes.literal_block))), 0)

    def test_the_diagram_source_is_html_escaped(self) -> None:
        source = 'flowchart LR\n    a["x & <y>"] --> b'
        document = _transform(
            nodes.literal_block(source, source, language=mermaid.LANGUAGE)
        )

        rendered = next(document.findall(nodes.raw)).astext()
        self.assertIn("&amp;", rendered)
        self.assertIn("&lt;y&gt;", rendered)
        self.assertNotIn("<y>", rendered)

    def test_other_languages_stay_literal_blocks(self) -> None:
        document = _transform(nodes.literal_block("echo hi", "echo hi", language="bash"))

        self.assertEqual(len(list(document.findall(nodes.raw))), 0)
        self.assertEqual(len(list(document.findall(nodes.literal_block))), 1)

    def test_setup_registers_the_transform_and_both_scripts(self) -> None:
        app = mock.Mock()

        meta = mermaid.setup(app)

        app.add_post_transform.assert_called_once_with(mermaid.MermaidFences)
        self.assertEqual(
            [call.args[0] for call in app.add_js_file.call_args_list],
            ["js/mermaid.min.js", "js/mermaid-init.js"],
        )
        self.assertTrue(meta["parallel_read_safe"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
