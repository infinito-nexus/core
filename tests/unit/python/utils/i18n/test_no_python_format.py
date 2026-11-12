"""A percent sign in prose must not make a catalog uncompilable.

xgettext counts a space as a format flag, so ``95% confidence`` parses as the
directive ``% c``. Every translation moves the following word, msgfmt then reads
``% V`` and refuses the catalog. The writer marks such entries
``no-python-format``; the negative cases below are shapes taken from the
documentation catalogs.
"""

from __future__ import annotations

import unittest

from babel.messages.catalog import Catalog

from utils.i18n.catalog import render
from utils.i18n.placeholders import carries_placeholder


class TestCarriesPlaceholder(unittest.TestCase):
    def test_a_bare_conversion(self) -> None:
        self.assertTrue(carries_placeholder("deployed %s"))

    def test_a_named_conversion(self) -> None:
        self.assertTrue(carries_placeholder("deployed %(app)s"))

    def test_an_integer_conversion(self) -> None:
        self.assertTrue(carries_placeholder("%d apps"))

    def test_any_plural_form_is_enough(self) -> None:
        self.assertTrue(carries_placeholder(("one app", "%d apps")))

    def test_a_percentage_in_prose(self) -> None:
        self.assertFalse(carries_placeholder("reach at least 95% confidence"))

    def test_a_quoted_jinja_block(self) -> None:
        self.assertFalse(carries_placeholder("wrap it in `{% if enabled %}`"))

    def test_a_percent_encoded_url(self) -> None:
        self.assertFalse(carries_placeholder("see /repo%2FCONTRIBUTING.md"))

    def test_a_plural_of_prose(self) -> None:
        self.assertFalse(carries_placeholder(("one at 95% load", "many")))


class TestRenderSuppressesTheFalseFlag(unittest.TestCase):
    def _flags(self, msgid: str, msgstr: str) -> set[str]:
        catalog = Catalog(locale="de")
        catalog.add(msgid, msgstr)
        render(catalog)
        return next(m.flags for m in catalog if m.id == msgid)

    def test_prose_loses_the_derived_flag(self) -> None:
        flags = self._flags("reach at least 95% confidence", "95% Vertrauen")

        self.assertIn("no-python-format", flags)
        self.assertNotIn("python-format", flags)

    def test_a_real_placeholder_keeps_its_flag(self) -> None:
        flags = self._flags("deployed %s", "%s ausgerollt")

        self.assertIn("python-format", flags)
        self.assertNotIn("no-python-format", flags)

    def test_the_written_catalog_carries_only_the_suppression(self) -> None:
        catalog = Catalog(locale="de")
        catalog.add("reach at least 95% confidence", "95% Vertrauen")

        written = render(catalog).decode("utf-8")

        self.assertIn("#, no-python-format\n", written)
        self.assertNotIn(", python-format", written)


if __name__ == "__main__":
    unittest.main()
