from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from babel.messages.catalog import Catalog
from babel.messages.pofile import write_po
from docutils import nodes
from docutils.frontend import get_default_settings
from docutils.parsers.rst import Parser
from docutils.utils import new_document

from utils.cache.files import read_text

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

from infinito_docs.identity import docs_sphinx_identity  # noqa: E402

translated_nodes = importlib.import_module("infinito_docs.extensions.translated_nodes")

EXTENSION = "infinito_docs.extensions.translated_nodes"
MESSAGES = {
    "Page": "Seite",
    "Another sentence with *emphasis*.": "Ein weiterer Satz mit *Betonung*.",
}


def _build_german_page(
    root: Path, extensions: list[str]
) -> tuple[nodes.document, bytes, str]:
    """Build one translated Markdown page in German.

    Args:
        root: empty scratch directory.
        extensions: extensions loaded besides ``myst_parser``.

    Returns:
        The page's doctree as Sphinx reads it back, its raw pickle and the HTML.
    """
    from sphinx.application import Sphinx

    src = root / "src"
    catalogs = src / "locale" / "de" / "LC_MESSAGES"
    catalogs.mkdir(parents=True)
    (src / "conf.py").write_text(
        f"extensions = {['myst_parser', *extensions]!r}\n"
        "locale_dirs = ['locale']\n"
        "gettext_compact = 'docs'\n",
        encoding="utf-8",
    )
    (src / "index.md").write_text(
        "# Page\n\nAnother sentence with *emphasis*.\n", encoding="utf-8"
    )
    catalog = Catalog(locale="de")
    for msgid, msgstr in MESSAGES.items():
        catalog.add(msgid, msgstr)
    with (catalogs / "docs.po").open("wb") as handle:
        write_po(handle, catalog)
    app = Sphinx(
        str(src),
        str(src),
        str(root / "html"),
        str(root / "doctrees"),
        "html",
        confoverrides={"language": "de"},
        status=None,
        warning=None,
        freshenv=True,
    )
    app.build()
    with (root / "doctrees" / "index.doctree").open("rb") as handle:
        raw = handle.read()
    return (
        app.env.get_doctree("index"),
        raw,
        read_text(str(root / "html" / "index.html")),
    )


class TestAdoptTranslatedNodes(unittest.TestCase):
    def test_nodes_of_a_foreign_document_are_handed_to_the_page(self) -> None:
        settings = get_default_settings(Parser)
        page = new_document("/src/page.md", settings)
        msgstr = new_document("/src/page.md:3:<translated>", settings)
        paragraph = nodes.paragraph()
        text = nodes.Text("Ein weiterer Satz")
        page += paragraph
        paragraph += text
        paragraph.document = msgstr
        text.document = msgstr
        self.assertIs(paragraph.document, msgstr)
        self.assertIs(text.document, msgstr)

        translated_nodes.AdoptTranslatedNodes(page).apply()

        self.assertIs(paragraph.document, page)
        self.assertIs(text.document, page)

    def test_it_runs_right_after_the_sphinx_locale_transform(self) -> None:
        from sphinx.transforms.i18n import Locale

        self.assertEqual(
            translated_nodes.AdoptTranslatedNodes.default_priority,
            Locale.default_priority + 1,
        )

    def test_conf_loads_the_extension(self) -> None:
        with (
            patch.object(sys, "argv", ["sphinx-build"]),
            patch.dict("os.environ", docs_sphinx_identity(PROJECT_ROOT)),
        ):
            conf = importlib.import_module("infinito_docs.conf")

        self.assertIn(EXTENSION, conf.extensions)

    def test_a_translated_markdown_page_pickles_without_the_environment(self) -> None:
        with TemporaryDirectory() as td:
            doctree, raw, html = _build_german_page(Path(td), [EXTENSION])

        self.assertEqual(
            [node for node in doctree.findall() if node.document is not doctree],
            [],
        )
        self.assertNotIn(b"BuildEnvironment", raw)
        self.assertIn("Betonung", html)
        self.assertIn("Seite", html)


if __name__ == "__main__":
    unittest.main()
