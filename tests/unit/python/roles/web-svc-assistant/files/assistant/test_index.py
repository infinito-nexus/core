from __future__ import annotations

import asyncio
import unittest

from . import load

index = load("index")
sources = load("sources")


class StubEmbedder:
    def __init__(self, short_by: int = 0) -> None:
        self.short_by = short_by

    def embed(self, texts):
        return [[float(len(text)), 1.0] for text in texts][: len(texts) - self.short_by]


class MemoryStore:
    def __init__(self) -> None:
        self.rows = [("stale", [0.0])]

    async def replace(self, rows) -> None:
        self.rows = list(rows)


def document(text: str) -> sources.Document:
    return sources.Document(
        "platform", "Backups", "https://code.example/backup.md", text
    )


class TestPassages(unittest.TestCase):
    def test_a_document_is_cut_at_its_headings(self) -> None:
        cut = index.passages(
            document("# Backups\n\nNightly.\n\n## Restore\n\nFrom the page."), 500
        )
        self.assertEqual(
            [p.text for p in cut],
            ["# Backups\n\nNightly.", "## Restore\n\nFrom the page."],
        )

    def test_a_long_section_is_cut_at_line_ends(self) -> None:
        cut = index.passages(document("# A\n" + "line of text\n" * 10), 40)
        self.assertTrue(all(len(p.text) <= 40 for p in cut))
        self.assertGreater(len(cut), 1)

    def test_every_passage_is_masked(self) -> None:
        cut = index.passages(
            document("# Admin\n\nMail anna@example.org for access."), 500
        )
        self.assertNotIn("anna@example.org", cut[0].text)


class TestBuild(unittest.TestCase):
    def test_the_store_is_replaced_as_a_whole(self) -> None:
        store = MemoryStore()
        count = asyncio.run(
            index.build(
                [document("# A\n\nOne.\n\n# B\n\nTwo.")], StubEmbedder(), store, 500
            )
        )
        self.assertEqual(count, 2)
        self.assertEqual(
            [row[0].text for row in store.rows], ["# A\n\nOne.", "# B\n\nTwo."]
        )

    def test_a_short_embedding_answer_leaves_the_store_untouched(self) -> None:
        store = MemoryStore()
        with self.assertRaises(ValueError):
            asyncio.run(
                index.build(
                    [document("# A\n\nOne.")], StubEmbedder(short_by=1), store, 500
                )
            )
        self.assertEqual(store.rows, [("stale", [0.0])])


if __name__ == "__main__":
    unittest.main()
