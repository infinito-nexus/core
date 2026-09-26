from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT
from utils.meta.authors import author_names, role_authors
from utils.software import SOFTWARE_AUTHOR


class TestAuthorNames(unittest.TestCase):
    def test_the_credited_people_are_listed(self) -> None:
        self.assertIn(SOFTWARE_AUTHOR, author_names())

    def test_the_names_are_sorted_and_unique(self) -> None:
        names = author_names()

        self.assertEqual(list(names), sorted(names))
        self.assertEqual(len(names), len(set(names)))

    def test_every_name_is_declared_by_at_least_one_role(self) -> None:
        declared = set()
        for role_dir in sorted((PROJECT_ROOT / "roles").iterdir()):
            if role_dir.is_dir():
                declared.update(role_authors(role_dir))

        self.assertEqual(
            set(author_names()),
            declared,
            "the names come from galaxy_info.author, not from prose that could "
            "drift from the role metadata",
        )

    def test_a_role_crediting_several_people_yields_each_of_them(self) -> None:
        multi = [
            names
            for role_dir in sorted((PROJECT_ROOT / "roles").iterdir())
            if role_dir.is_dir() and len(names := role_authors(role_dir)) > 1
        ]

        self.assertTrue(multi, "no role credits more than one author any more")
        for names in multi:
            self.assertTrue(all(name and not name.startswith(" ") for name in names))


if __name__ == "__main__":
    unittest.main()
