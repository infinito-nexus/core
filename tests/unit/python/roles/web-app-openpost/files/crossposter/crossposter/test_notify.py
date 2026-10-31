from __future__ import annotations

import unittest
from email.message import EmailMessage

from crossposter import notify

ROW = {
    "route": "press-mastodon",
    "source_url": "https://microblog.example/@press/1",
    "network": "x",
    "target": "x-press",
    "state": "dead_lettered",
    "attempts": 8,
    "last_error": "https://api.twitter.com/2/tweets: HTTP 503 unavailable",
}


class TestReport(unittest.TestCase):
    def test_the_report_names_source_target_and_error(self) -> None:
        report = notify.report([ROW])
        for expected in (
            "https://microblog.example/@press/1",
            "x-press",
            "HTTP 503 unavailable",
            "dead_lettered",
            "press-mastodon",
        ):
            self.assertIn(expected, report)

    def test_the_message_carries_subject_and_recipients(self) -> None:
        message = notify.message(
            "crossposter@example.org", ("press@example.org", "pr@example.org"), [ROW]
        )
        self.assertIsInstance(message, EmailMessage)
        self.assertEqual(message["To"], "press@example.org, pr@example.org")
        self.assertIn("1", message["Subject"])
        self.assertIn("x-press", message.get_content())
