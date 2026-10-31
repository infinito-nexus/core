from __future__ import annotations

import json
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from crossposter.sources import mastodon

from utils.cache.files import read_text

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> object:
    return json.loads(read_text(str(FIXTURES / name)))


class FakeMastodon:
    def __init__(self, statuses: list[dict]) -> None:
        self.statuses = statuses
        self.queries: list[dict[str, str]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> object:
        parsed = urllib.parse.urlparse(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        if parsed.path == "/api/v1/accounts/lookup":
            return fixture("mastodon/account.json")
        self.queries.append(query)
        ordered = sorted(self.statuses, key=lambda status: int(status["id"]))
        limit = int(query["limit"])
        if "min_id" not in query:
            return ordered[::-1][:limit]
        newer = [
            status for status in ordered if int(status["id"]) > int(query["min_id"])
        ]
        return newer[:limit][::-1]


class TestParse(unittest.TestCase):
    def setUp(self) -> None:
        self.statuses = fixture("mastodon/statuses.json")

    def test_a_status_becomes_a_source_item(self) -> None:
        item = mastodon.parse_status(self.statuses[0], "mastodon")
        self.assertEqual(item.uri, self.statuses[0]["uri"])
        self.assertEqual(item.visibility, "public")
        self.assertIn("#fediverse", item.text)
        self.assertEqual(item.tags, ("fediverse",))
        self.assertEqual(item.cursor, self.statuses[0]["id"])

    def test_media_carries_type_and_alt_text(self) -> None:
        item = mastodon.parse_status(self.statuses[1], "mastodon")
        self.assertEqual(item.media[0].mime, "image/png")
        self.assertEqual(item.media[0].description, "A red square")

    def test_the_posting_application_is_kept_for_loop_prevention(self) -> None:
        self.assertEqual(
            mastodon.parse_status(self.statuses[2], "mastodon").application, "OpenPost"
        )

    def test_content_warnings_and_replies_are_kept(self) -> None:
        item = mastodon.parse_status(self.statuses[3], "mastodon")
        self.assertEqual(item.spoiler, "politics")
        self.assertEqual(item.in_reply_to, "109000000000000001")


class TestPolling(unittest.TestCase):
    def test_the_newest_status_becomes_the_activation_cursor(self) -> None:
        fake = FakeMastodon(fixture("mastodon/statuses.json"))
        with patch.object(mastodon.web, "get_json", fake):
            cursor = mastodon.MastodonSource(
                "https://microblog.example", "press", "token"
            ).newest_cursor()
        self.assertEqual(
            cursor, max(fake.statuses, key=lambda status: int(status["id"]))["id"]
        )

    def test_fetch_returns_newer_statuses_oldest_first_and_excludes_replies_and_boosts(
        self,
    ) -> None:
        fake = FakeMastodon(fixture("mastodon/statuses.json"))
        with patch.object(mastodon.web, "get_json", fake):
            items = mastodon.MastodonSource(
                "https://microblog.example", "press", "token"
            ).fetch("0")
        cursors = [int(item.cursor) for item in items]
        self.assertEqual(cursors, sorted(cursors))
        self.assertEqual(fake.queries[0]["exclude_replies"], "true")
        self.assertEqual(fake.queries[0]["exclude_reblogs"], "true")

    def test_fetch_pages_with_the_min_id_cursor(self) -> None:
        many = [
            dict(
                fixture("mastodon/statuses.json")[0],
                id=str(200 + index),
                uri=f"https://m/{index}",
            )
            for index in range(45)
        ]
        fake = FakeMastodon(many)
        with patch.object(mastodon.web, "get_json", fake):
            items = mastodon.MastodonSource(
                "https://microblog.example", "press", "token"
            ).fetch("0")
        self.assertEqual(len(items), 45)
        self.assertEqual(fake.queries[1]["min_id"], "239")

    def test_refresh_rereads_the_status_with_its_current_media(self) -> None:
        stale = mastodon.parse_status(fixture("mastodon/statuses.json")[1], "mastodon")
        current = dict(fixture("mastodon/statuses.json")[1])
        current["media_attachments"] = [
            dict(current["media_attachments"][0], url="https://m/optimised.png")
        ]
        asked: list[str] = []

        def get_json(url: str, headers: dict[str, str]) -> object:
            asked.append(urllib.parse.urlparse(url).path)
            return current

        with patch.object(mastodon.web, "get_json", get_json):
            fresh = mastodon.MastodonSource(
                "https://microblog.example", "press", "token"
            ).refresh(stale)
        self.assertEqual(asked, [f"/api/v1/statuses/{stale.cursor}"])
        self.assertEqual(fresh.media[0].url, "https://m/optimised.png")
        self.assertEqual(fresh.cursor, stale.cursor)
