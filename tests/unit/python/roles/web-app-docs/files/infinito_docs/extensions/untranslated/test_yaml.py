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

untranslated_yaml = importlib.import_module(
    "infinito_docs.extensions.untranslated.yaml"
)


def _document(source: str):
    document = new_document(source, get_default_settings(Parser))
    document.append(nodes.paragraph(text="name: sys-stk-front-proxy"))
    document.append(nodes.title(text="Heading"))
    return document


class TestUntranslatedYaml(unittest.TestCase):
    def test_every_text_node_of_a_yaml_page_is_untranslatable(self) -> None:
        document = _document(f"/src/roles/web-app-x/{ROLE_FILE_META_SERVICES}")

        untranslated_yaml.UntranslatedYaml(document).apply()

        flags = [
            node.get("translatable") for node in document.findall(nodes.TextElement)
        ]
        self.assertEqual(flags, [False, False])

    def test_other_pages_keep_their_translatable_text(self) -> None:
        document = _document("/src/docs/README.md")

        untranslated_yaml.UntranslatedYaml(document).apply()

        self.assertTrue(
            all(
                "translatable" not in node
                for node in document.findall(nodes.TextElement)
            )
        )

    def test_it_runs_before_the_sphinx_locale_transform(self) -> None:
        from sphinx.transforms.i18n import Locale

        self.assertLess(
            untranslated_yaml.UntranslatedYaml.default_priority, Locale.default_priority
        )


if __name__ == "__main__":
    unittest.main()
