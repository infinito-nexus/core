"""Unit test: the CI-state checks on recorded run records and a job log - stale
heads, inherited checks, idle rounds, live runs, unattributed failures and the
re-run command."""

from __future__ import annotations

import unittest

from agents.routines.tools.ci_state import (
    ci_active,
    idle_round,
    inherited_stale,
    rerun_command,
    triage_stale,
    unattributed,
)

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


if __name__ == "__main__":
    unittest.main()
