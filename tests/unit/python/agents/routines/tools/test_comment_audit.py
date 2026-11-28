"""Unit test: the diff audit flags narration comments and em-dash lines on a
recorded unified diff while leaving nocheck, shebang and param-doc comments and
plain code alone."""

from __future__ import annotations

import unittest

from agents.routines.tools.comment_audit import em_dashes, offending_comments

_DIFF = """diff --git a/role.py b/role.py
index 1111111..2222222 100644
--- a/role.py
+++ b/role.py
@@ -1,4 +1,9 @@
 import os
+# this explains what the next line does
+value = os.getenv("X")  # trailing narration
+result = compute()  # noqa: E501
+#!/usr/bin/env python3
+# Param: path the archive is written to
+clean = "no # comment here is inside a string"
+pure = compute_again()
-dropped = 1
"""

_EM_DIFF = """@@ -1 +1,2 @@
+docs say the value — the default — is read once
+plain = 1
"""


class TestCommentAudit(unittest.TestCase):
    def test_narration_comments_flagged(self) -> None:
        offending = offending_comments(_DIFF)
        self.assertIn("# this explains what the next line does", offending)
        self.assertTrue(any("trailing narration" in line for line in offending))

    def test_allowed_comments_not_flagged(self) -> None:
        offending = offending_comments(_DIFF)
        self.assertFalse(any("noqa" in line for line in offending))
        self.assertFalse(any(line.startswith("#!") for line in offending))
        self.assertFalse(any("Param:" in line for line in offending))

    def test_code_and_string_hash_not_flagged(self) -> None:
        offending = offending_comments(_DIFF)
        self.assertNotIn('clean = "no # comment here is inside a string"', offending)
        self.assertNotIn("pure = compute_again()", offending)

    def test_em_dash_lines_returned(self) -> None:
        lines = em_dashes(_EM_DIFF)
        self.assertEqual(len(lines), 1)
        self.assertIn("—", lines[0])

    def test_removed_lines_ignored(self) -> None:
        self.assertEqual(em_dashes("--- a/x\n-old — line\n"), [])


if __name__ == "__main__":
    unittest.main()
