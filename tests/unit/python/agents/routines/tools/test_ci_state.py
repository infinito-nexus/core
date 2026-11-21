"""Unit test: the CI-state checks on recorded run records and a job log - stale
heads, inherited checks, idle rounds, live runs, unattributed failures and the
re-run command."""

from __future__ import annotations

import unittest

from agents.routines.tools.ci_state import (
    CONTINUE,
    END,
    TRIAGE,
    WAIT,
    attribution,
    ci_active,
    evidence_run,
    idle_round,
    inherited_stale,
    iteration_action,
    liveness,
    next_round,
    rerun_command,
    starved,
    triage_stale,
    unattributed,
)
from agents.routines.tools.log_scan import change_ran

_404_LOG = '{"message":"Not Found","documentation_url":"https://docs.github.com"}\n'

_RUNNER_ONLY = """##[group]Run ./.github/actions/ci
##[endgroup]
##[error]Process completed with exit code 1.
"""

_REAL_FAILURE = """✗ test_login
    AssertionError: expected 200, got 500
##[error]Process completed with exit code 1.
"""


class TestCiState(unittest.TestCase):
    def test_triage_stale_on_head_mismatch(self) -> None:
        self.assertTrue(triage_stale("aaa111", "bbb222"))
        self.assertFalse(triage_stale("aaa111", "aaa111"))

    def test_inherited_checks_stale_on_same_sha(self) -> None:
        self.assertTrue(inherited_stale("deadbeef", "deadbeef"))
        self.assertFalse(inherited_stale("deadbeef", "cafef00d"))

    def test_idle_round_when_nothing_new(self) -> None:
        prev = {"red_job_ids": [7, 3], "heads": {"pr": "aaa"}, "comments": ["c1"]}
        cur = {"red_job_ids": [3, 7], "heads": {"pr": "aaa"}, "comments": ["c1"]}
        self.assertTrue(idle_round(prev, cur))

    def test_not_idle_when_a_comment_arrives(self) -> None:
        prev = {"red_job_ids": [7], "heads": {"pr": "aaa"}, "comments": []}
        cur = {"red_job_ids": [7], "heads": {"pr": "aaa"}, "comments": ["new"]}
        self.assertFalse(idle_round(prev, cur))

    def test_ci_active_on_unfinished_pull_request_run(self) -> None:
        runs = [
            {"event": "push", "head_sha": "aaa", "status": "completed"},
            {"event": "pull_request", "head_sha": "aaa", "status": "in_progress"},
        ]
        self.assertTrue(ci_active(runs, "aaa"))

    def test_ci_not_active_when_only_completed(self) -> None:
        runs = [{"event": "pull_request", "headSha": "aaa", "status": "completed"}]
        self.assertFalse(ci_active(runs, "aaa"))

    def test_unattributed_on_404_and_runner_only(self) -> None:
        self.assertTrue(unattributed(_404_LOG))
        self.assertTrue(unattributed(_RUNNER_ONLY))

    def test_attributed_when_a_line_is_citable(self) -> None:
        self.assertFalse(unattributed(_REAL_FAILURE))

    def test_rerun_command(self) -> None:
        self.assertEqual(rerun_command("12345"), "gh run rerun 12345")


_ROUND = {"red_job_ids": [11, 12], "heads": {"pr-7": "aaa"}, "comments": ["c1"]}
_STARVED_JOB = {
    "id": 901,
    "status": "completed",
    "conclusion": "cancelled",
    "steps": [],
    "runner_name": "",
}
_CANCELLED_RUN = {
    "id": 4711,
    "event": "pull_request",
    "head_sha": "aaa",
    "status": "completed",
    "conclusion": "cancelled",
}


class TestCiStateRouting(unittest.TestCase):
    def test_unattributed_job_asks_the_operator_for_the_rerun(self) -> None:
        self.assertEqual(
            attribution(_404_LOG, "4711"),
            {"verdict": "unattributed", "ask": "gh run rerun 4711"},
        )

    def test_attributed_job_cites_its_line_and_asks_nothing(self) -> None:
        verdict = attribution(_REAL_FAILURE, "4711")
        self.assertEqual(verdict["verdict"], "attributed")
        self.assertNotIn("ask", verdict)

    def test_two_identical_rounds_wait_instead_of_a_third(self) -> None:
        self.assertEqual(next_round(_ROUND, dict(_ROUND)), WAIT)
        self.assertEqual(WAIT, "make ci-wait")

    def test_a_new_head_starts_another_round(self) -> None:
        moved = {**_ROUND, "heads": {"pr-7": "bbb"}}
        self.assertEqual(next_round(_ROUND, moved), TRIAGE)

    def test_a_queued_run_is_followed_until_it_completed_with_nothing_new(
        self,
    ) -> None:
        batches = [
            (False, {"job-1"}),
            (False, set()),
            (False, {"job-1", "job-2"}),
            (True, {"job-1", "job-2", "job-3"}),
            (True, {"job-1", "job-2", "job-3"}),
        ]
        seen: set[str] = set()
        actions: list[str] = []
        for completed, failures in batches:
            new = failures - seen
            seen |= failures
            actions.append(
                iteration_action(source_completed=completed, new_evidence=bool(new))
            )
            if actions[-1] == END:
                break
        self.assertEqual(actions, [CONTINUE, WAIT, CONTINUE, CONTINUE, END])
        self.assertEqual(seen, {"job-1", "job-2", "job-3"})

    def test_the_evidence_follows_the_run_after_a_cancelled_one(self) -> None:
        runs = [
            {"id": 1, "head_sha": "old", "conclusion": "success"},
            {"id": 2, "head_sha": "fix", "conclusion": "cancelled"},
            {"id": 3, "head_sha": "merge", "conclusion": "success"},
        ]
        logs = {
            2: "",
            3: "  ✓  4 [chromium] › playwright.spec.js:12:3 › login keeps the cookie (3.1s)\n",
        }
        contains = {"old": False, "fix": True, "merge": True}
        run = evidence_run(runs, contains.__getitem__)
        self.assertEqual(run["id"], 3)
        self.assertEqual(
            change_ran(logs[run["id"]], "login keeps the cookie"),
            "✓  4 [chromium] › playwright.spec.js:12:3 › login keeps the cookie (3.1s)",
        )

    def test_no_run_with_the_fix_is_no_evidence(self) -> None:
        runs = [{"id": 1, "head_sha": "old", "conclusion": "success"}]
        self.assertIsNone(evidence_run(runs, lambda head: False))

    def test_a_job_without_steps_or_runner_is_starved(self) -> None:
        self.assertTrue(starved(_STARVED_JOB))
        ran = {**_STARVED_JOB, "steps": [{"name": "Set up job"}], "runner_name": "r1"}
        self.assertFalse(starved(ran))

    def test_a_head_left_cancelled_by_a_starved_job_is_not_active(self) -> None:
        self.assertTrue(starved(_STARVED_JOB))
        self.assertEqual(
            liveness([_CANCELLED_RUN], "aaa"),
            "CI not active for aaa: gh run rerun 4711",
        )

    def test_a_head_with_a_live_run_reports_nothing(self) -> None:
        live = {**_CANCELLED_RUN, "id": 4712, "status": "queued", "conclusion": None}
        self.assertIsNone(liveness([live, _CANCELLED_RUN], "aaa"))


if __name__ == "__main__":
    unittest.main()
