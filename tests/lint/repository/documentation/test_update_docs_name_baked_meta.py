"""Lint guard: every page that offers the compose ``mode=update`` reuse path
names the meta files the inventory bakes in.

``mode=update`` deploys the inventory as it was built, so after a change to
one of those files a green update proves nothing about the change. The compose
iteration routine routes such a change to a reinstall; a page that offers the
update path without naming them sends a reader the other way.
"""

from __future__ import annotations

import re
import unittest

from tests.lint.repository.documentation import PROJECT_ROOT
from utils.cache.files import read_text
from utils.roles.mapping import (
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_USERS,
    ROLE_FILE_META_VARIANTS,
)

BAKED = (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_META_USERS,
)
PAGES = (
    "docs/contributing/actions/deploy.md",
    "docs/contributing/actions/testing.md",
    "cli/administration/deploy/development/README.md",
    "agents/skills/i8-iterate-compose/SKILL.md",
)


def _names(text: str, path: str) -> bool:
    return re.search(rf"(?<![\w.-]){re.escape(path)}(?![\w.-])", text) is not None


class TestUpdateDocsNameBakedMeta(unittest.TestCase):
    def test_every_update_page_names_every_baked_meta_file(self) -> None:
        missing = [
            f"  - {page}: {path}"
            for page in PAGES
            for path in BAKED
            if not _names(read_text(str(PROJECT_ROOT / page)), path)
        ]
        self.assertFalse(
            missing,
            "pages offering mode=update leave out an inventory-baked meta file, "
            "after whose change an update deploys the old inventory:\n"
            + "\n".join(missing),
        )

    def test_every_listed_page_offers_the_update_path(self) -> None:
        for page in PAGES:
            with self.subTest(page=page):
                self.assertIn("mode=update", read_text(str(PROJECT_ROOT / page)))

    def test_a_bare_file_name_does_not_count_as_naming_the_path(self) -> None:
        self.assertFalse(_names("`services.yml`", ROLE_FILE_META_SERVICES))
        self.assertFalse(_names("meta/services.yml.j2", ROLE_FILE_META_SERVICES))
        self.assertTrue(_names("roles/x/meta/services.yml,", ROLE_FILE_META_SERVICES))


if __name__ == "__main__":
    unittest.main()
