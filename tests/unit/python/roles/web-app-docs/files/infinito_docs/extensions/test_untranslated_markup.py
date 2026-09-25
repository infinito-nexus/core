from __future__ import annotations

import importlib
import sys
import unittest

from docutils import nodes
from docutils.frontend import get_default_settings
from docutils.parsers.rst import Parser
from docutils.utils import new_document

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

untranslated_markup = importlib.import_module(
    "infinito_docs.extensions.untranslated_markup"
)

SOURCE = "/src/docs/testing.md"


def _paragraph(raw: str) -> nodes.paragraph:
    node = nodes.paragraph(raw, "")
    node += nodes.Text(raw)
    node.source = SOURCE
    node.line = 1
    return node


def _applied(*raws: str) -> list[nodes.paragraph]:
    document = new_document(SOURCE, get_default_settings(Parser))
    paragraphs = [_paragraph(raw) for raw in raws]
    for node in paragraphs:
        document += node
    untranslated_markup.UntranslatedMarkup(document).apply()
    return paragraphs


class TestUntranslatedMarkup(unittest.TestCase):
    def test_a_message_of_pure_markup_is_flagged(self) -> None:
        (node,) = _applied("[`e2e/`](e2e/)")

        self.assertIs(node["translatable"], False)

    def test_a_sentence_around_the_same_link_stays_translatable(self) -> None:
        (node,) = _applied("Run the tests under [`e2e/`](e2e/) first.")

        self.assertNotIn(
            "translatable",
            node,
            "only the word-free messages may be withheld from the translator",
        )

    def test_a_heading_that_is_only_a_brand_is_flagged(self) -> None:
        (node,) = _applied("**Mastodon**")

        self.assertIs(
            node["translatable"],
            False,
            "the product is called that in every language, and the translator "
            "had been turning it into Keycloak's Schluesselmantel",
        )

    def test_a_lone_code_span_is_flagged(self) -> None:
        (node,) = _applied("`CLEANUP_FORCE_KEEP`")

        self.assertIs(node["translatable"], False)

    def test_several_nodes_are_judged_one_by_one(self) -> None:
        markup, prose = _applied("[`lint/`](lint/)", "Structural lint checks.")

        self.assertIs(markup["translatable"], False)
        self.assertNotIn("translatable", prose)

    def test_the_markup_is_judged_and_not_the_rendered_text(self) -> None:
        document = new_document(SOURCE, get_default_settings(Parser))
        node = nodes.paragraph("[`e2e/`](e2e/)", "")
        reference = nodes.reference("", "", refuri="e2e/")
        reference += nodes.literal("`e2e/`", "e2e/")
        node += reference
        node.source = SOURCE
        node.line = 1
        document += node

        untranslated_markup.UntranslatedMarkup(document).apply()

        self.assertEqual(node.astext(), "e2e/")
        self.assertIs(
            node["translatable"],
            False,
            "sphinx extracts a paragraph's rawsource, so judging astext() would "
            "read 'e2e/', find a word in it and let the markup through",
        )

    def test_it_runs_before_the_sphinx_locale_transform(self) -> None:
        from sphinx.transforms.i18n import Locale

        self.assertLess(
            untranslated_markup.UntranslatedMarkup.default_priority,
            Locale.default_priority,
        )

    def test_a_checkout_without_the_predicate_changes_nothing(self) -> None:
        original = untranslated_markup.untranslatable
        untranslated_markup.untranslatable = None
        self.addCleanup(setattr, untranslated_markup, "untranslatable", original)

        (node,) = _applied("[`e2e/`](e2e/)")

        self.assertNotIn(
            "translatable",
            node,
            "the docs site builds arbitrary refs, and one predating utils/i18n "
            "must still build",
        )


if __name__ == "__main__":
    unittest.main()
