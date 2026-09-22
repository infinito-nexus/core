from __future__ import annotations

import importlib
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.roles.mapping import (
    ROLE_FILE_META_INFO,
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)
from utils.software import SOFTWARE_REPOSITORY

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-svc-api" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

repository = importlib.import_module("infinito_api.repository")
roles = importlib.import_module("infinito_api.roles")
i18n = importlib.import_module("infinito_api.i18n")

FILES = {
    "meta/categories.yml": """\
        roles:
          web:
            title: Web
            hanzi: 网络
            app:
              title: Applications
              description: Apps for users
              invokable: true
          sys:
            title: System
            invokable: false
        """,
    f"roles/web-app-x/{ROLE_FILE_META_MAIN}": """\
        galaxy_info:
          description: " A wiki "
          galaxy_tags: [wiki, 7]
        """,
    f"roles/web-app-x/{ROLE_FILE_META_INFO}": "logo:\n  class: fa-solid fa-book\n",
    f"roles/web-app-x/{ROLE_FILE_META_SERVICES}": "x:\n  lifecycle: beta\nredis:\n  enabled: false\n",
    "roles/web-app-x/meta/broken.yml": "key: [unclosed\n",
    f"roles/web-app-x/{ROLE_FILE_VARS_MAIN}": "application_id: web-app-x\n",
    "roles/web-app-x/README.md": "Intro\n\n# X Wiki\n",
    f"roles/sys-y/{ROLE_FILE_META_MAIN}": "galaxy_info: {}\n",
    "roles/no-meta/README.md": "# Nothing\n",
    "inventories/bundles/servers/hub/inventory.yml": """\
        all:
          vars:
            infinito:
              bundle:
                title: Hub
                description: A hub
                logo:
                  class: fa-solid fa-hub
                tags: [community]
          children:
            web-app-x: {}
            sys-y: {}
        """,
}


class TestRoleData(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        snapshot = root / "snapshot"
        for relative, content in FILES.items():
            path = snapshot / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(content), encoding="utf-8")
        (root / "data").mkdir()
        self.repo = repository.Repository(
            root / "data" / "repo.git",
            SOFTWARE_REPOSITORY,
            "off",
            snapshot,
        )
        self.repo.initialize()
        self.commit = self.repo.resolve("deployed")
        self.data = roles.RoleData(self.repo)
        self.english = i18n.Translator("en", {})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_only_roles_with_a_meta_main_are_listed(self) -> None:
        self.assertEqual(list(self.data.roles(self.commit)), ["sys-y", "web-app-x"])

    def test_summary_reads_every_field_from_the_role_files(self) -> None:
        self.assertEqual(
            self.data.summary(self.commit, "web-app-x", self.english),
            {
                "id": "web-app-x",
                "application_id": "web-app-x",
                "title": "X Wiki",
                "description": "A wiki",
                "categories": ["web", "web.app"],
                "invokable": True,
                "lifecycle": "beta",
                "logo": "fa-solid fa-book",
                "tags": ["wiki"],
            },
        )
        self.assertFalse(
            self.data.summary(self.commit, "sys-y", self.english)["invokable"]
        )

    def test_detail_carries_every_meta_file_and_marks_unparsable_ones(self) -> None:
        detail = self.data.detail(self.commit, "web-app-x", self.english)
        self.assertEqual(sorted(detail["meta"]), ["broken", "info", "main", "services"])
        self.assertIsNone(detail["meta"]["broken"])
        self.assertEqual(detail["vars"], {"application_id": "web-app-x"})

    def test_descriptions_and_categories_are_translated(self) -> None:
        german = i18n.Translator(
            "de",
            {
                ("role:web-app-x:description", "A wiki"): "Ein Wiki",
                ("category:web.app:title", "Applications"): "Anwendungen",
            },
        )
        self.assertEqual(
            self.data.summary(self.commit, "web-app-x", german)["description"],
            "Ein Wiki",
        )
        web = next(
            c for c in self.data.categories(self.commit, german) if c["id"] == "web"
        )
        self.assertEqual(
            [(c["id"], c["title"], c["invokable"]) for c in web["children"]],
            [("web.app", "Anwendungen", True)],
        )

    def test_bundles_list_their_roles(self) -> None:
        self.assertEqual(
            self.data.bundles(self.commit),
            [
                {
                    "id": "servers/hub",
                    "deploy_target": "servers",
                    "slug": "hub",
                    "title": "Hub",
                    "description": "A hub",
                    "logo": "fa-solid fa-hub",
                    "tags": ["community"],
                    "categories": [],
                    "role_ids": ["sys-y", "web-app-x"],
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
