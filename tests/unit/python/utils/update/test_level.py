from __future__ import annotations

import unittest

from utils.update.level import bump_level, diff_level, line_level

SHA_A = "3fa19f8b6d3eecbacbdbf79406e0f877ebe11e26"
SHA_B = "dc95a4d7e7e5531b1fdaa59528121afcffb8b3f0"


class TestBumpLevel(unittest.TestCase):
    def test_the_first_changed_number_sets_the_level(self) -> None:
        self.assertEqual(bump_level("1.2.3", "2.0.0"), "major")
        self.assertEqual(bump_level("v8.8.3-alpine", "v8.9.0-alpine"), "minor")
        self.assertEqual(bump_level("6.8.0", "6.8.1"), "patch")
        self.assertEqual(bump_level("2026.05.18.0", "2026.05.18.1"), "patch")
        self.assertEqual(bump_level("24.04", "26.04"), "major")

    def test_a_sha_or_a_numberless_side_is_major(self) -> None:
        self.assertEqual(bump_level(SHA_A, SHA_B), "major")
        self.assertEqual(bump_level(SHA_A, "v0.1.1"), "major")
        self.assertEqual(bump_level("latest", "1.0.0"), "major")

    def test_a_longer_version_with_the_same_prefix_is_patch(self) -> None:
        self.assertEqual(bump_level("1.2", "1.2.1"), "patch")


class TestLineLevel(unittest.TestCase):
    def test_the_first_differing_token_decides(self) -> None:
        self.assertEqual(
            line_level('    version: "1.2.3"', '    version: "1.3.0"'), "minor"
        )
        self.assertEqual(line_level("pkg==4.0.1", "pkg==4.0.2"), "patch")
        self.assertEqual(
            line_level("    runs-on: ubuntu-24.04", "    runs-on: ubuntu-26.04"),
            "major",
        )
        self.assertEqual(line_level(f"  ref: {SHA_A}", "  ref: v0.1.1"), "major")

    def test_unpaired_tokens_are_major(self) -> None:
        self.assertEqual(line_level("ref: main", "ref: v1.0.0"), "major")


class TestDiffLevel(unittest.TestCase):
    def test_the_highest_level_of_every_hunk_wins(self) -> None:
        diff = (
            "diff --git a/roles/a/meta/services.yml b/roles/a/meta/services.yml\n"
            "--- a/roles/a/meta/services.yml\n"
            "+++ b/roles/a/meta/services.yml\n"
            "@@ -3 +3 @@\n"
            '-  version: "1.2.3"\n'
            '+  version: "1.2.4"\n'
            "@@ -9 +9 @@\n"
            '-  version: "4.1.0"\n'
            '+  version: "4.2.0"\n'
        )
        self.assertEqual(diff_level(diff), "minor")

    def test_a_hunk_with_unequal_sides_is_major(self) -> None:
        diff = "@@ -3 +3,2 @@\n-  version: 1.0.0\n+  version: 1.0.1\n+  extra: 1\n"
        self.assertEqual(diff_level(diff), "major")

    def test_an_empty_diff_is_major(self) -> None:
        self.assertEqual(diff_level(""), "major")


if __name__ == "__main__":
    unittest.main()
