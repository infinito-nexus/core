"""Unit test: the rate-limit classifier names the jobs that hit toomanyrequests,
whether each used the mirror or the cache, and the jobs that did not fail."""

from __future__ import annotations

import unittest

from agents.routines.tools.rate_limit import EXTERNAL_STRUCTURAL, classify, report

_JOBS = {
    "build-via-mirror": """Pulling from the registry mirror docker.io
toomanyrequests: You have reached your pull rate limit.
""",
    "build-via-cache": """Pulling through the pull-through cache
429 Too Many Requests
""",
    "unit-tests": "42 passed in 3.1s\n",
}


class TestRateLimit(unittest.TestCase):
    def test_rate_limited_jobs_detected(self) -> None:
        result = classify(_JOBS)
        self.assertEqual(
            result["rate_limited"], ["build-via-mirror", "build-via-cache"]
        )
        self.assertEqual(result["passed"], ["unit-tests"])

    def test_mirror_and_cache_paths_split(self) -> None:
        result = classify(_JOBS)
        self.assertEqual(result["via_mirror"], ["build-via-mirror"])
        self.assertEqual(result["via_cache"], ["build-via-cache"])

    def test_a_seeded_rate_limit_is_external_but_structural(self) -> None:
        self.assertEqual(classify(_JOBS)["class"], EXTERNAL_STRUCTURAL)
        self.assertIsNone(classify({"unit-tests": _JOBS["unit-tests"]})["class"])

    def test_the_report_states_the_pull_path(self) -> None:
        self.assertEqual(
            report(classify(_JOBS)),
            [
                "build-via-mirror: external but structural, pulled through the mirror",
                "build-via-cache: external but structural, pulled through the cache",
            ],
        )

    def test_the_report_names_a_pull_outside_mirror_and_cache(self) -> None:
        direct = {"build-direct": "toomanyrequests: pull rate limit\n"}
        self.assertEqual(
            report(classify(direct)),
            [
                "build-direct: external but structural, pulled through neither the mirror nor the cache"
            ],
        )


if __name__ == "__main__":
    unittest.main()
