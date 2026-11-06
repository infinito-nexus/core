from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crossposter import openpost, web
from crossposter.config import Targets

ACCOUNTS = [
    {"id": "acc-x", "slug": "x-press", "platform": "x"},
    {"id": "acc-li", "slug": "linkedin-press", "platform": "linkedin"},
]
SOCIAL_SETS = [
    {
        "name": "Commercial",
        "accounts": [
            {"social_account_id": "acc-x", "platform": "x", "default_settings": {}},
            {
                "social_account_id": "acc-li",
                "platform": "linkedin",
                "default_settings": {"visibility": "PUBLIC"},
            },
        ],
    }
]


class FakeOpenPost:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, bytes | None]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict,
        body: bytes | None,
        accepted: tuple[int, ...],
    ) -> web.Response:
        self.calls.append((method, url, headers, body))
        path = url.split("/api/v1", 1)[-1]
        if path.startswith("/accounts"):
            return web.Response(200, {}, json.dumps(ACCOUNTS).encode())
        if path.startswith("/social-sets"):
            return web.Response(200, {}, json.dumps(SOCIAL_SETS).encode())
        if path == "/publications":
            return web.Response(
                201,
                {},
                json.dumps({"id": "pub-1", "revision": 1, "status": "draft"}).encode(),
            )
        if path == "/media/upload-session":
            session = {
                "media_id": "media-1",
                "complete_url": "/api/v1/media/upload-session/media-1/complete",
                "upload": {
                    "url": "/media/upload/media-1",
                    "method": "PUT",
                    "headers": {},
                },
            }
            return web.Response(200, {}, json.dumps(session).encode())
        if path.endswith("/complete"):
            completed = {"id": "media-0", "deduped": True}
            return web.Response(200, {}, json.dumps(completed).encode())
        return web.Response(200, {}, b"{}")


def client() -> openpost.OpenPost:
    return openpost.OpenPost(
        "http://openpost:8080", "publish.example", "op-token", "workspace-1"
    )


class TestDestinations(unittest.TestCase):
    def test_accounts_resolve_by_slug(self) -> None:
        with patch.object(openpost.web, "request", FakeOpenPost()):
            found = client().destinations(Targets(("linkedin-press",), ""))
        self.assertEqual(
            [(item.account_id, item.platform) for item in found],
            [("acc-li", "linkedin")],
        )

    def test_an_unknown_slug_is_refused(self) -> None:
        with (
            patch.object(openpost.web, "request", FakeOpenPost()),
            self.assertRaises(openpost.TargetError),
        ):
            client().destinations(Targets(("myspace-press",), ""))

    def test_a_social_set_expands_to_its_accounts_with_their_defaults(self) -> None:
        with patch.object(openpost.web, "request", FakeOpenPost()):
            found = client().destinations(Targets((), "Commercial"))
        self.assertEqual([item.slug for item in found], ["x-press", "linkedin-press"])
        self.assertEqual(found[1].settings, {"visibility": "PUBLIC"})

    def test_an_unknown_social_set_is_refused(self) -> None:
        with (
            patch.object(openpost.web, "request", FakeOpenPost()),
            self.assertRaises(openpost.TargetError),
        ):
            client().destinations(Targets((), "Nowhere"))


class TestRequests(unittest.TestCase):
    def test_create_sends_the_idempotency_key_and_the_alt_text(self) -> None:
        fake = FakeOpenPost()
        destination = openpost.Destination("acc-x", "x-press", "x", {})
        with patch.object(openpost.web, "request", fake):
            client().create(
                destination,
                "Title",
                "Body",
                "image_post",
                [("media-1", "A red square")],
                "crossposter-abc",
                {"crossposter_source": "https://microblog.example/@press/1"},
            )
        method, url, headers, body = fake.calls[-1]
        self.assertEqual(
            (method, url), ("POST", "http://openpost:8080/api/v1/publications")
        )
        self.assertEqual(headers["Idempotency-Key"], "crossposter-abc")
        self.assertEqual(headers["Authorization"], "Bearer op-token")
        payload = json.loads(body)
        self.assertEqual(
            payload["media"], [{"media_id": "media-1", "alt_text": "A red square"}]
        )
        self.assertEqual(payload["social_account_ids"], ["acc-x"])
        self.assertEqual(
            payload["metadata"],
            {"crossposter_source": "https://microblog.example/@press/1"},
        )

    def test_local_uploads_go_to_openpost_with_its_credentials(self) -> None:
        fake = FakeOpenPost()
        uploads: list[tuple[str, dict]] = []

        def upload(
            method: str,
            url: str,
            headers: dict,
            source: Path,
            accepted: tuple[int, ...],
        ) -> web.Response:
            uploads.append((url, headers))
            return web.Response(200, {}, b"")

        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "a.jpg"
            image.write_bytes(b"\xff\xd8 image")
            with (
                patch.object(openpost.web, "request", fake),
                patch.object(openpost.web, "upload", upload),
            ):
                media = client().upload(image, "a.jpg", "image/jpeg")
        self.assertEqual(media, "media-0")
        self.assertEqual(uploads[0][0], "http://openpost:8080/media/upload/media-1")
        self.assertEqual(uploads[0][1]["Authorization"], "Bearer op-token")
        self.assertTrue(
            fake.calls[-1][1].endswith("/media/upload-session/media-1/complete")
        )


class TestPublicMedia(unittest.TestCase):
    def answers(self, states: list[list[dict]]) -> list[str]:
        asked: list[str] = []
        self.validated: list[str] = []

        def request(method, url, headers, body, accepted) -> web.Response:
            if method == "POST":
                self.validated.append(url)
                return web.Response(200, {}, b'{"valid": true, "issues": []}')
            asked.append(url)
            media = states[min(len(asked), len(states)) - 1]
            return web.Response(200, {}, json.dumps({"media": media}).encode())

        self.request = request
        return asked

    def test_publishing_waits_until_every_medium_is_public(self) -> None:
        asked = self.answers(
            [
                [{"public_url_checked_at": None}],
                [{"public_url_checked_at": "now", "public_url_ready": False}],
                [{"public_url_checked_at": "now", "public_url_ready": True}],
            ]
        )
        with (
            patch.object(openpost.web, "request", self.request),
            patch.object(openpost.time, "sleep", lambda seconds: None),
        ):
            client().await_media("pub-1")
        self.assertEqual(len(asked), 3)
        self.assertTrue(asked[0].endswith("/publications/pub-1"))
        self.assertEqual(len(self.validated), 3)
        self.assertTrue(self.validated[0].endswith("/publications/pub-1/validate"))

    def test_media_that_never_turns_public_is_a_transient_error(self) -> None:
        self.answers([[{"public_url_checked_at": "now", "public_url_ready": False}]])
        with (
            patch.object(openpost.web, "request", self.request),
            patch.object(openpost.time, "sleep", lambda seconds: None),
            self.assertRaises(web.RequestError) as raised,
        ):
            client().await_media("pub-1")
        self.assertTrue(raised.exception.transient)

    def test_a_video_also_waits_for_its_analysis(self) -> None:
        public = {"public_url_checked_at": "now", "public_url_ready": True}
        asked = self.answers(
            [
                [{**public, "mime_type": "video/mp4", "analysis_status": "pending"}],
                [{**public, "mime_type": "video/mp4", "analysis_status": "ready"}],
            ]
        )
        with (
            patch.object(openpost.web, "request", self.request),
            patch.object(openpost.time, "sleep", lambda seconds: None),
        ):
            client().await_media("pub-1")
        self.assertEqual(len(asked), 2)

    def test_an_image_needs_no_analysis(self) -> None:
        self.assertTrue(
            openpost.publishable(
                {
                    "public_url_checked_at": "now",
                    "public_url_ready": True,
                    "mime_type": "image/jpeg",
                    "analysis_status": "pending",
                }
            )
        )
