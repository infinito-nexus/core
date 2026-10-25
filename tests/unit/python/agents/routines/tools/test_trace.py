"""Unit test: the trace reader returns the navigation chain in order and reads a
Set-Cookie header into its attributes without ever exposing the cookie name or
value."""

from __future__ import annotations

import unittest

from agents.routines.tools.trace import cookie_attributes, navigation_chain

_ENTRIES = [
    {"type": "navigate", "url": "https://cloud.example.com/login"},
    {"type": "action", "apiName": "page.fill"},
    {"type": "navigated", "url": "https://cloud.example.com/dashboard"},
    {"type": "console", "text": "ready"},
]

_SET_COOKIE = "session=s3cr3t-token-abc; Path=/; HttpOnly; SameSite=Lax; Secure; Max-Age=3600"


class TestNavigationChain(unittest.TestCase):
    def test_chain_in_order(self) -> None:
        self.assertEqual(
            navigation_chain(_ENTRIES),
            ["https://cloud.example.com/login", "https://cloud.example.com/dashboard"],
        )

    def test_empty_when_no_navigation(self) -> None:
        self.assertEqual(navigation_chain([{"type": "console", "text": "x"}]), [])


class TestCookieAttributes(unittest.TestCase):
    def test_attributes_parsed(self) -> None:
        attributes = cookie_attributes(_SET_COOKIE)
        self.assertEqual(
            attributes,
            {
                "Path": "/",
                "HttpOnly": "",
                "SameSite": "Lax",
                "Secure": "",
                "Max-Age": "3600",
            },
        )

    def test_name_and_value_never_exposed(self) -> None:
        attributes = cookie_attributes(_SET_COOKIE)
        self.assertNotIn("session", attributes)
        self.assertNotIn("s3cr3t-token-abc", attributes.values())


if __name__ == "__main__":
    unittest.main()
