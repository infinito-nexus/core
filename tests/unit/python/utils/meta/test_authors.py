from __future__ import annotations

import unittest

from utils.meta.authors import author_names
from utils.roles.credits import author_urls
from utils.software import SOFTWARE_AUTHOR


class TestAuthorNames(unittest.TestCase):
    def test_the_credited_people_are_listed(self) -> None:
        self.assertIn(SOFTWARE_AUTHOR, author_names())

    def test_the_names_are_sorted_and_unique(self) -> None:
        names = author_names()

        self.assertEqual(list(names), sorted(names))
        self.assertEqual(len(names), len(set(names)))

    def test_it_carries_exactly_the_keys_of_the_url_map(self) -> None:
        self.assertEqual(
            set(author_names()),
            set(author_urls()),
            "the names are the map's keys, not a second list that could drift "
            "from the Credits sections they are derived from",
        )


if __name__ == "__main__":
    unittest.main()
