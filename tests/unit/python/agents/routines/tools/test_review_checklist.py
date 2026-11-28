from __future__ import annotations

import unittest

from agents.routines.tools.review_checklist import (
    authored_by,
    checklist_failures,
    protected_paths_touched,
    specs_without_control,
)
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN


def _failures(**overrides) -> list[str]:
    fields = {
        "evidence": "make test: 12 passed",
        "unbacked": [],
        "offending": [],
        "changed_files": [f"roles/web-app-gitea/{ROLE_FILE_TASKS_MAIN}"],
    }
    fields.update(overrides)
    return checklist_failures(**fields)


class TestChecklist(unittest.TestCase):
    def test_a_clean_pull_request_passes(self) -> None:
        self.assertEqual(_failures(), [])

    def test_red_fixture_a_missing_evidence_comment_fails(self) -> None:
        self.assertEqual(_failures(evidence="  \n"), ["no evidence comment"])

    def test_an_unbacked_number_fails(self) -> None:
        self.assertEqual(
            _failures(unbacked=["42 %"]), ["numbers without evidence: 42 %"]
        )

    def test_a_forbidden_comment_fails(self) -> None:
        self.assertEqual(
            _failures(offending=["# step one"]), ["1 forbidden comment(s) added"]
        )

    def test_a_protected_path_fails(self) -> None:
        self.assertEqual(
            _failures(changed_files=["agents/firewall/roles.yml"]),
            ["touches protected paths: agents/firewall/roles.yml"],
        )


class TestProtectedPaths(unittest.TestCase):
    def test_every_protected_path_is_caught(self) -> None:
        touched = [
            "agents/firewall/roles.yml",
            "agents/routines/reviewer.py",
            "utils/firewall/compile.py",
            ".github/workflows/entry-pr-change-orchestrate.yml",
            "roles/web-app-gitea/AGENTS.md",
            "agents/roles/tuner/SOUL.md",
        ]

        self.assertEqual(protected_paths_touched(touched), touched)

    def test_a_lookalike_is_not_protected(self) -> None:
        self.assertEqual(
            protected_paths_touched(["agents/firewall-notes.md", "AGENTS.md.bak"]), []
        )


class TestAuthorship(unittest.TestCase):
    def test_the_own_pull_request_is_recognised_case_insensitively(self) -> None:
        self.assertTrue(authored_by("Rvwr0abc", "rvwr0abc"))

    def test_another_author_is_reviewed(self) -> None:
        self.assertFalse(authored_by("impl0abc", "rvwr0abc"))

    def test_an_unknown_author_is_no_own_pull_request(self) -> None:
        self.assertFalse(authored_by("", ""))


class TestNegativeControls(unittest.TestCase):
    def test_a_spec_without_a_control_is_named(self) -> None:
        self.assertEqual(
            specs_without_control(
                ["a.spec.js", "b.spec.js"], {"a.spec.js": (True, True)}
            ),
            ["b.spec.js"],
        )

    def test_a_half_control_does_not_count(self) -> None:
        self.assertEqual(
            specs_without_control(["a.spec.js"], {"a.spec.js": (True, False)}),
            ["a.spec.js"],
        )

    def test_no_changed_spec_needs_no_control(self) -> None:
        self.assertEqual(specs_without_control([], {}), [])


if __name__ == "__main__":
    unittest.main()
