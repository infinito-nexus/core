"""Unit test: the Prometheus reader returns probe_success and the HTTP status
for the series matching an app, by instance substring or app label, and reports
a false success with no status when nothing matches."""

from __future__ import annotations

import unittest

from agents.routines.tools.prometheus import probe

_METRICS = """# HELP probe_success Displays whether the probe was successful
# TYPE probe_success gauge
probe_success{instance="https://cloud.example.com",job="blackbox"} 1
probe_http_status_code{instance="https://cloud.example.com",job="blackbox"} 200
probe_success{instance="https://chat.example.com",job="blackbox"} 0
probe_http_status_code{instance="https://chat.example.com",job="blackbox"} 503
probe_success{app="akaunting"} 1
probe_http_status_code{app="akaunting"} 204
"""


class TestProbe(unittest.TestCase):
    def test_match_by_instance_substring(self) -> None:
        self.assertEqual(
            probe(_METRICS, "cloud"),
            {"probe_success": True, "probe_http_status_code": 200},
        )

    def test_failing_probe(self) -> None:
        self.assertEqual(
            probe(_METRICS, "chat"),
            {"probe_success": False, "probe_http_status_code": 503},
        )

    def test_match_by_app_label(self) -> None:
        self.assertEqual(
            probe(_METRICS, "akaunting"),
            {"probe_success": True, "probe_http_status_code": 204},
        )

    def test_unmatched_app(self) -> None:
        self.assertEqual(
            probe(_METRICS, "nonexistent"),
            {"probe_success": False, "probe_http_status_code": None},
        )


if __name__ == "__main__":
    unittest.main()
