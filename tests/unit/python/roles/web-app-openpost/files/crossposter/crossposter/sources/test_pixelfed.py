from __future__ import annotations

import json
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from crossposter.sources import mastodon, pixelfed

from utils.cache.files import read_text

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> object:
    return json.loads(read_text(str(FIXTURES / name)))


class TestPixelfed(unittest.TestCase):
    def test_pixelfed_polls_without_the_unsupported_reblog_filter(self) -> None:
        queries: list[dict[str, str]] = []

        def fake(url: str, headers: dict[str, str]) -> object:
            parsed = urllib.parse.urlparse(url)
            if parsed.path == "/api/v1/accounts/lookup":
                return {"id": "42"}
            queries.append(dict(urllib.parse.parse_qsl(parsed.query)))
            return fixture("pixelfed_statuses.json")

        with patch.object(mastodon.web, "get_json", fake):
            items = pixelfed.PixelfedSource(
                "https://picture.example", "press", "token"
            ).fetch("0")
        self.assertNotIn("exclude_reblogs", queries[0])
        self.assertEqual(queries[0]["exclude_replies"], "true")
        self.assertEqual([item.platform for item in items], ["pixelfed", "pixelfed"])

    def test_a_reblog_is_flagged_for_the_route_filter(self) -> None:
        statuses = {
            status["id"]: status for status in fixture("pixelfed_statuses.json")
        }
        own = mastodon.parse_status(statuses["801"], pixelfed.PixelfedSource.platform)
        boosted = mastodon.parse_status(
            statuses["802"], pixelfed.PixelfedSource.platform
        )
        self.assertFalse(own.reblog)
        self.assertTrue(boosted.reblog)
        self.assertEqual(own.media[0].mime, "image/jpeg")
        self.assertEqual(own.media[0].description, "Sunset over the harbour")
