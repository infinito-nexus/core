"""Unit test: the JUnit reader returns the first failing testcase's name,
message and system-out from a recorded report, and None when all cases pass."""

from __future__ import annotations

import unittest

from agents.routines.tools.junit import first_failure

_WITH_FAILURE = """<testsuites>
  <testsuite name="e2e" tests="3" failures="1" errors="0">
    <testcase classname="login" name="admin signs in" time="0.4"/>
    <testcase classname="login" name="password rejected" time="0.3">
      <failure message="expected 200, got 500">AssertionError at login.spec.js:12</failure>
      <system-out>POST /login -&gt; 500</system-out>
    </testcase>
  </testsuite>
</testsuites>
"""

_WITH_ERROR = """<testsuite name="unit" tests="1" errors="1">
  <testcase classname="db" name="connects">
    <error message="connection refused">OperationalError</error>
  </testcase>
</testsuite>
"""

_ALL_PASS = """<testsuite name="unit" tests="2">
  <testcase classname="a" name="one"/>
  <testcase classname="a" name="two"/>
</testsuite>
"""


class TestFirstFailure(unittest.TestCase):
    def test_failure_fields(self) -> None:
        result = first_failure(_WITH_FAILURE)
        self.assertEqual(result["name"], "password rejected")
        self.assertEqual(result["message"], "expected 200, got 500")
        self.assertEqual(result["system_out"], "POST /login -> 500")

    def test_error_counts_as_failure(self) -> None:
        result = first_failure(_WITH_ERROR)
        self.assertEqual(result["name"], "connects")
        self.assertEqual(result["message"], "connection refused")

    def test_none_when_all_pass(self) -> None:
        self.assertIsNone(first_failure(_ALL_PASS))


if __name__ == "__main__":
    unittest.main()
