"""Unit test: the failed-job reader keeps only the failed jobs of a recorded
gh-api jobs response, as id/name pairs, and ignores running and passed ones."""

from __future__ import annotations

import unittest

from agents.routines.tools.jobs import failed_jobs

_RUNS_JSON = """{
  "total_count": 4,
  "jobs": [
    {"id": 101, "name": "build", "conclusion": "success"},
    {"id": 102, "name": "test (compose)", "conclusion": "failure"},
    {"id": 103, "name": "lint", "conclusion": null},
    {"id": 104, "name": "test (swarm)", "conclusion": "failure"}
  ]
}"""

_BARE_LIST = """[
  {"id": 7, "name": "deploy", "conclusion": "failure"},
  {"id": 8, "name": "notify", "conclusion": "success"}
]"""


class TestFailedJobs(unittest.TestCase):
    def test_only_failures_returned(self) -> None:
        self.assertEqual(
            failed_jobs(_RUNS_JSON),
            [
                {"id": 102, "name": "test (compose)"},
                {"id": 104, "name": "test (swarm)"},
            ],
        )

    def test_bare_list_accepted(self) -> None:
        self.assertEqual(failed_jobs(_BARE_LIST), [{"id": 7, "name": "deploy"}])

    def test_no_failures(self) -> None:
        self.assertEqual(
            failed_jobs('{"jobs": [{"id": 1, "name": "ok", "conclusion": "success"}]}'),
            [],
        )


if __name__ == "__main__":
    unittest.main()
