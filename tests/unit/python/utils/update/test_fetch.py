from __future__ import annotations

import unittest
import unittest.mock as mock

from utils.update import fetch as module

BODIES = {
    "https://example.test/tags": b"core v1.0.0",
    "https://example.test/compose": b"image: example/app:v1.0.0-1.29",
}


class TestDocuments(unittest.TestCase):
    def setUp(self) -> None:
        module.document.cache_clear()
        self.addCleanup(module.document.cache_clear)

    def test_several_documents_are_read_as_one_text(self) -> None:
        with mock.patch.object(module, "get", side_effect=BODIES.__getitem__):
            self.assertEqual(
                module.documents(list(BODIES)),
                "core v1.0.0\nimage: example/app:v1.0.0-1.29",
            )
            self.assertEqual(
                module.documents("https://example.test/tags"), "core v1.0.0"
            )

    def test_a_document_is_fetched_once_per_run(self) -> None:
        with mock.patch.object(module, "get", side_effect=BODIES.__getitem__) as get:
            module.documents(list(BODIES))
            module.documents("https://example.test/tags")
            module.documents("https://example.test/compose")

        self.assertEqual(get.call_count, 2)

    def test_a_failed_fetch_is_tried_again(self) -> None:
        with (
            mock.patch.object(module, "get", side_effect=OSError("down")),
            self.assertRaises(OSError),
        ):
            module.documents("https://example.test/tags")
        with mock.patch.object(module, "get", side_effect=BODIES.__getitem__):
            self.assertEqual(
                module.documents("https://example.test/tags"), "core v1.0.0"
            )


if __name__ == "__main__":
    unittest.main()
