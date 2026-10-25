"""Unit test: the ref probe confirms a printed __file__ lies under the reference
worktree, proving the negative control imported the ref's module."""

from __future__ import annotations

import unittest

from agents.routines.tools.ref_probe import imported_from_ref

_REF = "/tmp/ref-worktree/core"


class TestRefProbe(unittest.TestCase):
    def test_file_under_ref_is_from_ref(self) -> None:
        self.assertTrue(
            imported_from_ref(f"{_REF}/agents/routines/maintainer.py", _REF)
        )

    def test_file_in_current_tree_is_not_from_ref(self) -> None:
        self.assertFalse(
            imported_from_ref(
                "/home/u/worktrees/feature/agents/routines/maintainer.py", _REF
            )
        )

    def test_exact_path_counts(self) -> None:
        self.assertTrue(imported_from_ref(_REF, _REF))


if __name__ == "__main__":
    unittest.main()
