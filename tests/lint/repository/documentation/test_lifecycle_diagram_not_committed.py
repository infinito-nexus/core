"""Lint: the lifecycle diagram is rendered by the docs build, never committed."""

from __future__ import annotations

import unittest

from cli.build.docs import markers
from cli.build.docs.lifecycle import BEGIN, DOC, END
from utils.cache.files import PROJECT_ROOT, read_text


def committed_block_problems(text: str) -> list[str]:
    """What keeps *text* from carrying an empty, well-placed marker pair.

    Args:
        text: the committed ``lifecycle.md``.

    Returns:
        One line per problem, empty when the file is clean.
    """
    return markers.committed_block_problems(text, begin=BEGIN, end=END)


class TestLifecycleDiagramNotCommitted(unittest.TestCase):
    def test_the_committed_block_is_empty_and_the_markers_are_in_place(self) -> None:
        problems = committed_block_problems(read_text(str(PROJECT_ROOT / DOC)))
        self.assertEqual(
            problems,
            [],
            f"{DOC} must keep exactly one empty {BEGIN} ... {END} block; the "
            "documentation build renders the diagram into it:\n  "
            + "\n  ".join(problems),
        )

    def test_a_committed_diagram_line_is_reported(self) -> None:
        text = f"# T\n{BEGIN}\n```mermaid\nflowchart LR\n```\n{END}\n"
        self.assertEqual(3, len(committed_block_problems(text)))

    def test_blank_lines_between_the_markers_are_accepted(self) -> None:
        self.assertEqual([], committed_block_problems(f"{BEGIN}\n\n{END}\n"))

    def test_a_missing_marker_is_reported(self) -> None:
        self.assertEqual(1, len(committed_block_problems(f"# T\n{BEGIN}\n")))
        self.assertEqual(1, len(committed_block_problems("# T\n")))

    def test_a_repeated_or_reversed_marker_is_reported(self) -> None:
        repeated = f"{BEGIN}\n{END}\n{BEGIN}\n{END}\n"
        self.assertEqual(1, len(committed_block_problems(repeated)))
        self.assertIn("follows", committed_block_problems(f"{END}\n{BEGIN}\n")[0])


if __name__ == "__main__":
    unittest.main()
