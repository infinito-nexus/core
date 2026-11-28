from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.i18n.extract import MENU_FILE

TREE = load_yaml_any(str(PROJECT_ROOT / MENU_FILE))["portfolio_menu_categories"]
TOP_LEVEL = [
    "Communication & Collaboration",
    "Community & Social",
    "Business",
    "Knowledge & Content",
    "Artificial Intelligence",
    "Administration",
    "Leisure",
    "Help",
    "Other",
]


def _walk(folders: dict, parent: str):
    """Yield ``(path, entry)`` for every folder of the tree, depth first.

    Args:
        folders: one level of ``portfolio_menu_categories``.
        parent: the path of the folder holding ``folders``, ``""`` at the top.
    """
    for name, entry in folders.items():
        path = f"{parent}/{name}" if parent else name
        yield path, entry
        yield from _walk(entry.get("children") or {}, path)


class TestMenuCategories(unittest.TestCase):
    def test_the_top_level_follows_the_agreed_taxonomy(self):
        self.assertEqual(list(TREE), TOP_LEVEL)

    def test_every_folder_has_a_description_and_an_icon(self):  # nocheck: test.text-presence -- walks the parsed menu YAML tree  # fmt: skip
        offenders = [
            path
            for path, entry in _walk(TREE, "")
            if not (
                isinstance(entry.get("description"), str)
                and entry["description"].strip()
            )
            or not (
                isinstance(entry.get("icon"), str) and entry["icon"].startswith("fa")
            )
        ]

        self.assertEqual(offenders, [])

    def test_every_leaf_folder_assigns_applications_by_tags(self):
        offenders = [
            path
            for path, entry in _walk(TREE, "")
            if not entry.get("children")
            and not entry.get("fallback")
            and not (
                isinstance(entry.get("tags"), list)
                and entry["tags"]
                and all(isinstance(tag, str) and tag for tag in entry["tags"])
            )
        ]

        self.assertEqual(offenders, [])

    def test_only_the_other_folder_takes_the_unmatched_applications(self):
        fallbacks = [path for path, entry in _walk(TREE, "") if entry.get("fallback")]

        self.assertEqual(fallbacks, ["Other"])
        self.assertNotIn("tags", TREE["Other"])
        self.assertNotIn("children", TREE["Other"])


if __name__ == "__main__":
    unittest.main()
