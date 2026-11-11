"""The oracle's report names the file every failing entry was extracted from.

Runs the suite's own helpers with the extraction lookup mocked, so no model,
gateway or repository walk is involved.
"""

from __future__ import annotations

import unittest
from unittest import mock

from tests.oracle import test_translation_score as suite

WHERE = "docs/de"
README = "roles/web-app-wiki/README.md"
FINDING = "0 below the middle level 1: 'The wiki' -> 'Das Auto'"


class OffenceTestCase(unittest.TestCase):
    def test_the_line_names_the_catalog_the_file_and_the_finding(self) -> None:
        line = suite.offence(WHERE, README, FINDING)

        self.assertEqual(line, f"{WHERE} ({README}): {FINDING}")


class OriginTestCase(unittest.TestCase):
    def test_a_core_entry_is_named_by_the_file_its_context_points_at(self) -> None:
        self.assertEqual(
            suite.origin("core", "role:web-app-wiki:description", "A wiki"),
            "roles/web-app-wiki/meta/main.yml",
        )

    def test_a_docs_entry_names_every_file_that_carries_it(self) -> None:
        with mock.patch.object(
            suite, "docs_sources", return_value=["docs/wiki.md", README]
        ) as sources:
            named = suite.origin("docs", None, "The wiki")

        sources.assert_called_once_with(suite.PROJECT_ROOT, "The wiki")
        self.assertEqual(named, f"docs/wiki.md, {README}")

    def test_a_docs_entry_no_file_carries_is_named_as_unsourced(self) -> None:
        with mock.patch.object(suite, "docs_sources", return_value=[]):
            self.assertEqual(suite.origin("docs", None, "Gone"), suite.UNSOURCED)

    def test_the_fixture_names_the_module_that_holds_it(self) -> None:
        self.assertEqual(suite.FIXTURE_ORIGIN, "tests/oracle/test_translation_score.py")


if __name__ == "__main__":
    unittest.main()
