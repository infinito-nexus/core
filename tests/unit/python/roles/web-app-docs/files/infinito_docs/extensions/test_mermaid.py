from __future__ import annotations

import importlib
import sys
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory

from docutils import nodes
from docutils.frontend import get_default_settings
from docutils.parsers.rst import Parser
from docutils.utils import new_document

from utils.cache.files import read_text

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

mermaid = importlib.import_module("infinito_docs.extensions.mermaid")

EXTENSION = "infinito_docs.extensions.mermaid"
DIAGRAM = 'flowchart LR\n    a["a"] --> b["b"]'
SCRIPT_SOURCES = tuple(f'src="_static/{script}' for script in mermaid.SCRIPTS)


def _transform(*blocks: nodes.literal_block):
    document = new_document("<test>", get_default_settings(Parser))
    for block in blocks:
        document.append(block)
    mermaid.MermaidFences(document).run()
    return document


def _build_site(root: Path) -> tuple[str, str]:
    """Build a page without a diagram and a page with one.

    Args:
        root: empty scratch directory.

    Returns:
        The HTML of the plain root page and of the diagram page.
    """
    from sphinx.application import Sphinx

    src = root / "src"
    src.mkdir()
    (src / "conf.py").write_text(
        f"extensions = {['myst_parser', EXTENSION]!r}\n", encoding="utf-8"
    )
    (src / "index.md").write_text(
        "# Plain\n\n```bash\necho hi\n```\n", encoding="utf-8"
    )
    (src / "diagram.md").write_text(
        f"---\norphan: true\n---\n\n# Diagram\n\n```mermaid\n{DIAGRAM}\n```\n",
        encoding="utf-8",
    )
    app = Sphinx(
        str(src),
        str(src),
        str(root / "html"),
        str(root / "doctrees"),
        "html",
        status=None,
        warning=None,
        freshenv=True,
    )
    app.build()
    return (
        read_text(str(root / "html" / "index.html")),
        read_text(str(root / "html" / "diagram.html")),
    )


class TestMermaidFences(unittest.TestCase):
    def test_a_mermaid_block_becomes_a_raw_diagram(self) -> None:
        document = _transform(
            nodes.literal_block(DIAGRAM, DIAGRAM, language=mermaid.LANGUAGE)
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
        document = _transform(
            nodes.literal_block("echo hi", "echo hi", language="bash")
        )

        self.assertEqual(len(list(document.findall(nodes.raw))), 0)
        self.assertEqual(len(list(document.findall(nodes.literal_block))), 1)


class TestDiagramScripts(unittest.TestCase):
    def test_setup_adds_no_script_to_every_page(self) -> None:
        app = unittest.mock.Mock()

        meta = mermaid.setup(app)

        app.add_post_transform.assert_called_once_with(mermaid.MermaidFences)
        app.connect.assert_called_once_with(
            "html-page-context", mermaid.add_diagram_scripts
        )
        app.add_js_file.assert_not_called()
        self.assertTrue(meta["parallel_read_safe"])

    def test_a_page_with_a_diagram_gets_both_scripts_in_order(self) -> None:
        app = unittest.mock.Mock()
        doctree = _transform(
            nodes.literal_block(DIAGRAM, DIAGRAM, language=mermaid.LANGUAGE)
        )

        mermaid.add_diagram_scripts(app, "page", "page.html", {}, doctree)

        self.assertEqual(
            [call.args[0] for call in app.add_js_file.call_args_list],
            ["js/mermaid.min.js", "js/mermaid-init.js"],
        )

    def test_a_page_without_a_diagram_gets_no_script(self) -> None:
        app = unittest.mock.Mock()
        doctree = _transform(nodes.literal_block("echo hi", "echo hi", language="bash"))

        mermaid.add_diagram_scripts(app, "page", "page.html", {}, doctree)

        app.add_js_file.assert_not_called()

    def test_a_generated_page_without_a_doctree_gets_no_script(self) -> None:
        app = unittest.mock.Mock()

        mermaid.add_diagram_scripts(app, "genindex", "genindex.html", {}, None)

        app.add_js_file.assert_not_called()

    def test_a_built_site_loads_the_scripts_only_where_a_diagram_is_drawn(
        self,
    ) -> None:
        with TemporaryDirectory() as td:
            plain, diagram = _build_site(Path(td))

        self.assertIn('<pre class="mermaid">', diagram)
        positions = [diagram.find(source) for source in SCRIPT_SOURCES]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))
        for source in SCRIPT_SOURCES:
            self.assertNotIn(source, plain)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
