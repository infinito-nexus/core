from __future__ import annotations

import json
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from crossposter.sources import peertube

from utils.cache.files import read_text

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> object:
    return json.loads(read_text(str(FIXTURES / name)))


def fake_get_json(url: str, headers: dict[str, str]) -> object:
    parsed = urllib.parse.urlparse(url)
    if parsed.path.startswith("/api/v1/videos/"):
        detail = fixture("peertube/video_detail.json")
        return dict(detail, uuid=parsed.path.rsplit("/", 1)[-1])
    start = int(dict(urllib.parse.parse_qsl(parsed.query))["start"])
    listing = fixture("peertube/videos.json")
    return dict(listing, data=listing["data"][start:])


class TestParse(unittest.TestCase):
    def test_a_published_public_video_carries_title_description_tags_and_one_mp4(
        self,
    ) -> None:
        video = fixture("peertube/videos.json")["data"][0]
        item = peertube.parse_video(video, fixture("peertube/video_detail.json"))
        self.assertEqual(item.title, video["name"])
        self.assertTrue(item.text.startswith("Full description"))
        self.assertEqual(item.tags, ("talk", "fediverse"))
        self.assertEqual(item.media[0].mime, "video/mp4")
        self.assertEqual(item.media[0].size, 52_428_800)
        self.assertTrue(item.media[0].url.endswith("-1080.mp4"))
        self.assertEqual(item.cursor, video["publishedAt"])

    def test_only_published_public_videos_pass(self) -> None:
        videos = fixture("peertube/videos.json")["data"]
        self.assertEqual(
            [peertube.published_public(video) for video in videos], [True, False, False]
        )


class TestPolling(unittest.TestCase):
    def test_the_newest_video_becomes_the_activation_cursor(self) -> None:
        with patch.object(peertube.web, "get_json", fake_get_json):
            cursor = peertube.PeerTubeSource(
                "https://video.example", "press_channel", "token"
            ).newest_cursor()
        self.assertEqual(cursor, "2026-10-22T10:30:00.000Z")

    def test_fetch_forwards_only_newer_published_public_videos_oldest_first(
        self,
    ) -> None:
        with patch.object(peertube.web, "get_json", fake_get_json):
            items = peertube.PeerTubeSource(
                "https://video.example", "press_channel", "token"
            ).fetch("2026-10-22T09:00:00.000Z")
        self.assertEqual([item.title for item in items], ["Conference talk"])
