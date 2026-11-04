"""Unit test: the branch-prefix check accepts the allowed kinds and refuses the
rest by the first path segment."""

from __future__ import annotations

import unittest

from agents.routines.tools.branch_prefix import prefix_ok


class TestBranchPrefix(unittest.TestCase):
    def test_allowed_prefixes_pass(self) -> None:
        for branch in (
            "feature/agents",
            "fix/login-500",
            "update/pins",
            "chore/cleanup",
            "dependabot/pip/requests-2.32.0",
            "alert-autofix/ql-123",
        ):
            self.assertTrue(prefix_ok(branch), branch)

    def test_unknown_prefix_refused(self) -> None:
        self.assertFalse(prefix_ok("wip/experiment"))
        self.assertFalse(prefix_ok("feature-no-slash"))


if __name__ == "__main__":
    unittest.main()
