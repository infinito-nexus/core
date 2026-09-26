from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_README

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

roles_overview = importlib.import_module("infinito_docs.generators.roles_overview")


def _role(roles_dir: Path, name: str, meta: str, readme: str | None = None) -> None:
    meta_file = roles_dir / name / ROLE_FILE_META_MAIN
    meta_file.parent.mkdir(parents=True)
    meta_file.write_text(meta, encoding="utf-8")
    if readme is not None:
        (roles_dir / name / ROLE_FILE_README).write_text(readme, encoding="utf-8")


class TestRolesOverviewGenerator(unittest.TestCase):
    def test_roles_are_grouped_by_tag_and_titled_from_their_readme(self) -> None:
        with TemporaryDirectory() as td:
            roles = Path(td) / "roles"
            _role(
                roles,
                "web-app-demo",
                "galaxy_info:\n  description: Demo role\n  galaxy_tags: [wiki, docs]\n",
                "Intro\n# Demo Title\n\nText\n",
            )
            _role(roles, "web-app-bare", "galaxy_info:\n  description: Bare\n")
            (roles / "no-meta").mkdir()
            (roles / ".hidden").mkdir()
            output = Path(td) / "out" / "overview.json"

            roles_overview.main(
                ["--roles-dir", str(roles), "--output-file", str(output)]
            )
            categories = json.loads(read_text(str(output)))

        self.assertEqual(
            {
                tag: [role["title"] for role in roles]
                for tag, roles in categories.items()
            },
            {
                "wiki": ["Demo Title"],
                "docs": ["Demo Title"],
                "uncategorized": ["web-app-bare"],
            },
        )
        self.assertEqual(
            categories["wiki"][0],
            {
                "name": "web-app-demo",
                "title": "Demo Title",
                "description": "Demo role",
                "link": "roles/web-app-demo/README.md",
                "tags": ["wiki", "docs"],
            },
        )

    def test_unreadable_meta_is_skipped(self) -> None:
        with TemporaryDirectory() as td:
            roles = Path(td) / "roles"
            _role(roles, "web-app-broken", "galaxy_info: [unclosed\n")
            _role(roles, "web-app-list", "- not a mapping\n")

            self.assertEqual(roles_overview.collect_roles_by_tag(roles), {})


if __name__ == "__main__":
    unittest.main()
