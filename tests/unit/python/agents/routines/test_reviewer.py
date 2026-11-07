"""Unit test: the reviewer routine routes an agent pull request to its verdict
on fixture state, walking the steps the way the compiled graph does."""

from __future__ import annotations

import unittest

from agents.routines import reviewer
from utils.roles.mapping import ROLE_FILE_PLAYWRIGHT_SPEC

_STEPS = {step.id: step for step in reviewer.STEPS}
_SPEC = f"roles/web-app-gitea/{ROLE_FILE_PLAYWRIGHT_SPEC}"
_CLEAN = {
    "pr_author": "impl0abc",
    "reviewer_account": "rvwr0abc",
    "pr_text": "12 passed",
    "evidence": "make test: 12 passed",
    "diff": "",
    "changed_files": [_SPEC],
    "changed_specs": [_SPEC],
    "negative_controls": {_SPEC: (True, True)},
    "ci_log": "✓ gitea spec checks the change",
    "change_marker": "gitea spec checks the change",
    "L1": "✨ clean",
}


def _walk(state: dict) -> list[str]:
    path = ["T1"]
    step = _STEPS["T1"]
    while step.kind != "terminal":
        if step.fn is not None:
            state = step.fn(state)
        if step.branches:
            labels = dict(step.branches)
            chosen = state.get(step.id, step.branches[0][0])
            target = labels.get(chosen, step.branches[0][1])
        else:
            target = step.nxt
        path.append(target)
        step = _STEPS[target]
    return path


def _verdict(**overrides) -> str:
    return _walk({**_CLEAN, **overrides})[-1]


class TestReviewerVerdict(unittest.TestCase):
    def test_a_clean_pull_request_gets_recommend_merge(self) -> None:
        self.assertEqual(_verdict(), "D6")

    def test_red_fixture_a_missing_evidence_comment_gets_changes_requested(
        self,
    ) -> None:
        path = _walk({**_CLEAN, "evidence": ""})

        self.assertEqual(path[-1], "D5")
        self.assertNotIn("L1", path)

    def test_the_own_pull_request_is_skipped(self) -> None:
        path = _walk({**_CLEAN, "pr_author": "RVWR0ABC"})

        self.assertEqual(path, ["T1", "D1", "D0"])

    def test_a_new_spec_without_a_negative_control_gets_changes_requested(
        self,
    ) -> None:
        self.assertEqual(_verdict(negative_controls={}), "D5")

    def test_a_pull_request_without_a_spec_needs_no_control(self) -> None:
        self.assertEqual(_verdict(changed_specs=[], negative_controls={}), "D6")

    def test_a_protected_path_gets_no_recommend_merge(self) -> None:
        self.assertEqual(_verdict(changed_files=["agents/firewall/roles.yml"]), "D5")

    def test_a_ci_log_without_the_change_gets_changes_requested(self) -> None:
        self.assertEqual(_verdict(ci_log="nothing relevant"), "D5")

    def test_problems_the_model_found_get_changes_requested(self) -> None:
        self.assertEqual(_verdict(L1="🐞 problems"), "D5")


if __name__ == "__main__":
    unittest.main()
