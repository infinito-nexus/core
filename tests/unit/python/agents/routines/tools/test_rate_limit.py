"""Unit test: the rate-limit classifier names the jobs that hit toomanyrequests,
whether each used the mirror or the cache, and the jobs that did not fail."""

from __future__ import annotations

import unittest

from agents.routines.tools.rate_limit import classify

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


if __name__ == "__main__":
    unittest.main()
