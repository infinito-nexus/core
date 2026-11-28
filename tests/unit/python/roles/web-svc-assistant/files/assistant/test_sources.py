from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from . import load

sources = load("sources")


class TestDocuments(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "platform" / "administration").mkdir(parents=True)
        (self.root / "platform" / "administration" / "backup.md").write_text(
            "# Backups\n\nNightly.\n"
        )
        (self.root / "platform" / "administration" / "notes.txt").write_text(
            "not markdown\n"
        )
        (self.root / "platform" / "inventories").mkdir()
        (self.root / "platform" / "inventories" / "README.md").write_text(
            "# Inventory\n"
        )
        (self.root / "tenant" / "acme").mkdir(parents=True)
        (self.root / "tenant" / "acme" / "faq.md").write_text("No heading here.\n")
        (self.root / "tenant" / "acme" / "leak.md").symlink_to(
            self.root / "platform" / "administration" / "backup.md"
        )
        manifest = [
            {
                "name": "platform",
                "root": "platform",
                "url": "https://code.example/docs/",
            },
            {"name": "acme", "root": "tenant/acme", "url": "https://acme.example/help"},
            {"name": "outside", "root": "../elsewhere", "url": "https://x.example"},
        ]
        (self.root / sources.MANIFEST).write_text(json.dumps(manifest))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def found(self):
        return sources.documents(self.root, sources.load_manifest(self.root))

    def test_only_indexable_documents_of_each_source_are_read(self) -> None:
        self.assertEqual(
            [d.url for d in self.found()],
            [
                "https://code.example/docs/administration/backup.md",
                "https://acme.example/help/faq.md",
            ],
        )

    def test_the_title_is_the_first_heading_else_the_file_name(self) -> None:
        self.assertEqual([d.title for d in self.found()], ["Backups", "faq"])

    def test_each_document_names_its_source(self) -> None:
        self.assertEqual([d.source for d in self.found()], ["platform", "acme"])


if __name__ == "__main__":
    unittest.main()
