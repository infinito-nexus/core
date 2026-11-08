from __future__ import annotations

import unittest

from cli.build.docs.readme.architecture import _volumes_legend


class TestVolumesLegend(unittest.TestCase):
    def test_each_table_row_is_one_item_with_the_columns_of_the_header(self):
        rows = [line for line in _volumes_legend() if line.startswith("|")]
        self.assertEqual([3, 3, 3, 3], [row.count("|") for row in rows])
        self.assertIn("role not pinned | shared over NFS |", rows[2])

    def test_the_explanation_below_the_table_is_one_paragraph(self):
        prose = [line for line in _volumes_legend() if line and line[0] != "|"]
        self.assertEqual(1, len(prose))
        self.assertTrue(prose[0].startswith("All four conditions must hold"))
        self.assertTrue(prose[0].endswith("move data without saying so."))


if __name__ == "__main__":
    unittest.main()
