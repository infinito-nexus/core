from __future__ import annotations

import unittest
import unittest.mock as mock
from typing import ClassVar

from utils.update import checksum as module

DIGEST = "6484afc32872a3aa16cac9a76ba1816a1ed4cc870a6593cc2e17757750f518b2"
STALE = "a43bc1afd446f9c4cc66ac5dd45d02e8d65e26fc5344ec0ef787f88d6ddb6f9e"


class TestRewrite(unittest.TestCase):
    SOURCE: ClassVar[dict[str, str]] = {
        "key": "mermaid_version",
        "checksum_key": "mermaid_sha256",
        "checksum_url": "https://example.test/mermaid@{version}/mermaid.min.js",
    }

    def _lines(self) -> list[str]:
        return [
            "docs:\n",
            "  mermaid_version: 12.1.0\n",
            f"  mermaid_sha256: {STALE}\n",
            "other:\n",
            f"  mermaid_sha256: {STALE}\n",
        ]

    def test_the_digest_of_the_new_version_replaces_the_one_in_its_block(self) -> None:
        lines = self._lines()

        with mock.patch.object(module, "digest", return_value=DIGEST) as fetched:
            module.rewrite(lines, "docs", self.SOURCE, "12.2.0")

        fetched.assert_called_once_with(
            "https://example.test/mermaid@12.2.0/mermaid.min.js"
        )
        self.assertEqual(lines[2], f"  mermaid_sha256: {DIGEST}\n")
        self.assertEqual(lines[4], f"  mermaid_sha256: {STALE}\n")

    def test_a_pin_without_a_declared_checksum_fetches_nothing(self) -> None:
        lines = self._lines()

        with mock.patch.object(module, "digest") as fetched:
            module.rewrite(lines, "docs", {"key": "mermaid_version"}, "12.2.0")

        fetched.assert_not_called()
        self.assertEqual(lines, self._lines())


class TestProblems(unittest.TestCase):
    CONFIG: ClassVar[dict[str, str]] = {
        "mermaid_version": "12.1.0",
        "mermaid_sha256": STALE,
    }

    def test_a_complete_declaration_reports_nothing(self) -> None:
        self.assertEqual(
            module.problems(
                "web-app-docs/docs",
                "mermaid_version",
                self.CONFIG,
                TestRewrite.SOURCE,
            ),
            [],
        )

    def test_a_missing_key_and_a_url_without_the_placeholder_are_reported(self) -> None:
        found = module.problems(
            "web-app-docs/docs",
            "mermaid_version",
            self.CONFIG,
            {"checksum_key": "absent", "checksum_url": "https://example.test/x.js"},
        )

        self.assertEqual(len(found), 2)
        self.assertIn("names no key beside the version pin", found[0])
        self.assertIn(module.PLACEHOLDER, found[1])


if __name__ == "__main__":
    unittest.main()
