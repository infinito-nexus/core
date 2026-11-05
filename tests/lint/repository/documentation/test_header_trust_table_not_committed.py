"""Lint: the header-trust table is rendered by the docs build, never committed."""

from __future__ import annotations

import re
import unittest

from cli.build.docs import markers
from cli.build.docs.header_trust import BEGIN, DOC, END
from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.header_trust import header_trust_exemptions, header_trust_roles

CANDIDATES_INTRO = "Candidates that trust no header"
_ROW_ROLE = re.compile(r"^\|\s*`(?P<role>(?:web|svc|sys|dsk)-[a-z0-9-]+)`", re.MULTILINE)


def candidate_roles(text: str) -> list[str]:
    """Returns the roles of the hand-written candidates table after *END*.

    Args:
        text: the committed ``rbac.md``.
    """
    tail = text.split(END, 1)[1]
    table = tail.split(CANDIDATES_INTRO, 1)[1].split("\n\n", 2)[1]
    return [match["role"] for match in _ROW_ROLE.finditer(table)]


class TestHeaderTrustTableNotCommitted(unittest.TestCase):
    def test_the_committed_block_is_empty_and_the_markers_are_in_place(self) -> None:
        problems = markers.committed_block_problems(
            read_text(str(PROJECT_ROOT / DOC)), begin=BEGIN, end=END
        )
        self.assertEqual(
            [],
            problems,
            f"{DOC} must keep exactly one empty {BEGIN} ... {END} block; the "
            "documentation build renders the header-trust table into it:\n  "
            + "\n  ".join(problems),
        )

    def test_a_committed_table_line_is_reported(self) -> None:
        text = f"# T\n{BEGIN}\n| Role |\n|---|\n{END}\n"
        self.assertEqual(
            2, len(markers.committed_block_problems(text, begin=BEGIN, end=END))
        )

    def test_the_hand_written_candidates_stay_undetected(self) -> None:
        """A candidate the scan finds belongs in the rendered table instead."""
        roles_dir = PROJECT_ROOT / "roles"
        candidates = candidate_roles(read_text(str(PROJECT_ROOT / DOC)))
        self.assertTrue(candidates, "no hand-written candidate found to check")
        derived = set(header_trust_roles(roles_dir)) | set(
            header_trust_exemptions(roles_dir)
        )
        self.assertEqual([], sorted(set(candidates) & derived))

    def test_the_candidate_parser_reads_only_the_table(self) -> None:
        text = (
            f"{BEGIN}\n{END}\n\n{CANDIDATES_INTRO}:\n\n| Role | Why |\n|---|---|\n"
            "| `web-app-a` | x |\n\n| `web-app-b` | later table |\n"
        )
        self.assertEqual(["web-app-a"], candidate_roles(text))


if __name__ == "__main__":
    unittest.main()
