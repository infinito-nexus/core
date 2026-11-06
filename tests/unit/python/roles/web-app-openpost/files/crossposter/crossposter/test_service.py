from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from crossposter import service, store, web
from crossposter.config import (
    Config,
    Filters,
    OpenPostSettings,
    Retry,
    Route,
    Source,
    Targets,
)
from crossposter.notify import Mail
from crossposter.openpost import Destination
from crossposter.sources import Media, SourceItem

DESTINATIONS = [
    Destination("acc-x", "x-press", "x", {}),
    Destination("acc-li", "linkedin-press", "linkedin", {}),
]


def post(number: int, tags: tuple[str, ...] = ()) -> SourceItem:
    return SourceItem(
        uri=f"https://microblog.example/users/press/statuses/{number}",
        url=f"https://microblog.example/@press/{number}",
        platform="mastodon",
        text=f"Post {number}",
        visibility="public",
        tags=tags,
        media=(),
        in_reply_to="",
        reblog=False,
        spoiler="",
        application="",
        cursor=str(number),
    )


SOURCE_TOKEN = {"Authorization": "Bearer source-token"}


class TestMediaCredentials(unittest.TestCase):
    def test_media_on_the_source_origin_gets_the_source_token(self) -> None:
        self.assertEqual(
            service.credentials_for(
                "https://microblog.example",
                "https://microblog.example/system/media/1.png",
                SOURCE_TOKEN,
            ),
            SOURCE_TOKEN,
        )

    def test_media_in_an_object_store_never_sees_the_source_token(self) -> None:
        self.assertEqual(
            service.credentials_for(
                "https://microblog.example",
                "https://s3.example/mastodon/media/1.png",
                SOURCE_TOKEN,
            ),
            {},
        )


def picture(number: int, url: str) -> SourceItem:
    return replace(post(number), media=(Media(url, "image/jpeg", "", 0),))


class FakeSource:
    def __init__(self, items: list[SourceItem]) -> None:
        self.items = items
        self.headers: dict[str, str] = {}
        self.fresh_url = ""

    def refresh(self, item: SourceItem) -> SourceItem:
        if not self.fresh_url:
            return item
        return replace(
            item, media=tuple(replace(m, url=self.fresh_url) for m in item.media)
        )

    def newest_cursor(self) -> str:
        return "100"

    def fetch(self, cursor: str) -> list[SourceItem]:
        return [item for item in self.items if int(item.cursor) > int(cursor)]


class FakeStore:
    def __init__(self) -> None:
        self.cursors: dict[str, str] = {}
        self.items: list[dict] = []
        self.notified: list[int] = []

    def cursor(self, route: str) -> str | None:
        return self.cursors.get(route)

    def advance(
        self, route: str, cursor: str, enqueued: list[tuple[SourceItem, str, str]]
    ) -> None:
        for item, target, network in enqueued:
            if any(
                row["source_uri"] == item.uri and row["target"] == target
                for row in self.items
            ):
                continue
            self.items.append(
                {
                    "id": len(self.items) + 1,
                    "route": route,
                    "source_uri": item.uri,
                    "source_url": item.url,
                    "target": target,
                    "network": network,
                    "state": "pending",
                    "payload": json.loads(store.item_to_json(item)),
                    "publication_id": "",
                    "attempts": 0,
                    "resends": 0,
                    "last_error": "",
                    "delay": 0.0,
                    "notified": False,
                }
            )
        self.cursors[route] = cursor

    def due(self) -> list[dict]:
        return [dict(row) for row in self.items if row["state"] == "pending"]

    def open_publications(self) -> list[dict]:
        return [
            dict(row) for row in self.items if row["state"] in ("drafted", "submitted")
        ]

    def unnotified(self) -> list[dict]:
        return [
            dict(row)
            for row in self.items
            if row["state"] in ("failed", "dead_lettered") and not row["notified"]
        ]

    def update(
        self,
        row_id: int,
        state: str,
        publication_id: str,
        attempts: int,
        error: str,
        delay_seconds: float,
    ) -> None:
        row = self.items[row_id - 1]
        row.update(
            state=state,
            publication_id=publication_id,
            attempts=attempts,
            last_error=error,
            delay=delay_seconds,
        )

    def resend(
        self, row_id: int, attempts: int, error: str, delay_seconds: float
    ) -> None:
        row = self.items[row_id - 1]
        row.update(
            state="pending",
            resends=row["resends"] + 1,
            publication_id="",
            attempts=attempts,
            last_error=error,
            delay=delay_seconds,
        )

    def mark_notified(self, row_id: int) -> None:
        self.items[row_id - 1]["notified"] = True


REJECTED = {
    "status": "failed",
    "error_retryable": False,
    "error_http_status": 400,
    "delivery": {"terminal_reason": "provider_rejected"},
}
UNAVAILABLE = {
    "status": "failed",
    "error_retryable": False,
    "error_http_status": 503,
    "delivery": {"recovery_action": "manual_resolution"},
}


class FakeOpenPost:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, str]] = []
        self.metadata: list[dict] = []
        self.published: list[str] = []
        self.failure: web.RequestError | None = None
        self.publish_failure: web.RequestError | None = None
        self.outcome: list[dict] = []

    def destinations(self, targets: Targets) -> list[Destination]:
        return DESTINATIONS

    def create(self, destination, title, text, profile, media, key, metadata) -> dict:
        if self.failure:
            raise self.failure
        self.created.append((destination.account_id, text, key))
        self.metadata.append(metadata)
        return {"id": f"pub-{len(self.created)}", "revision": 1, "status": "draft"}

    def publication(self, publication_id: str) -> dict:
        return {"id": publication_id, "revision": 1, "status": "draft"}

    def upload(self, source: Path, filename: str, mime: str) -> str:
        return f"media-{filename}"

    def publish_now(self, publication: dict) -> None:
        if self.publish_failure:
            raise self.publish_failure
        self.published.append(publication["id"])

    def renditions(self, publication_id: str) -> list[dict]:
        return self.outcome


def route(mode: str) -> Route:
    return Route(
        name="press",
        source=Source("mastodon", "https://microblog.example", "press", "token"),
        filters=Filters(frozenset({"public"}), True, True, frozenset(), "any"),
        targets=Targets(("x-press", "linkedin-press"), ""),
        mode=mode,
        attribution={"default": "{text}\n\n{source_url}", "x": "{text}"},
    )


class ServiceFixture:
    def build(
        self, mode: str, items: list[SourceItem], database: FakeStore | None = None
    ) -> tuple[service.Service, FakeStore, FakeOpenPost]:
        folder = tempfile.mkdtemp()
        config = Config(
            openpost=OpenPostSettings(
                "http://openpost:8080", "publish.example", "op-token", "workspace-1"
            ),
            dsn="postgresql://unused",
            mail=Mail(
                "mail.example", 587, "starttls", "", "", "crossposter@example.org"
            ),
            heartbeat_file=str(Path(folder) / "heartbeat"),
            poll_interval_seconds=60,
            opt_out_tag="nocrosspost",
            retry=Retry(3, 30, 3600),
            recipients=("press@example.org",),
            routes=(route(mode),),
        )
        database = database or FakeStore()
        client = FakeOpenPost()
        runner = service.Service(config, database, client)
        runner.sources["press"] = FakeSource(items)
        return runner, database, client


class TestDetection(ServiceFixture, unittest.TestCase):
    def test_activation_forwards_no_existing_post(self) -> None:
        runner, database, _ = self.build("auto", [post(1), post(2)])
        runner.tick()
        self.assertEqual(database.cursors["press"], "100")
        self.assertEqual(database.items, [])

    def test_new_posts_are_queued_per_target_and_the_opt_out_is_skipped(self) -> None:
        runner, database, _ = self.build(
            "review", [post(101), post(102, ("nocrosspost",))]
        )
        database.cursors["press"] = "100"
        runner.detect(runner.routes["press"])
        self.assertEqual(
            [(row["source_uri"][-3:], row["target"]) for row in database.items],
            [("101", "acc-x"), ("101", "acc-li")],
        )
        self.assertEqual(database.cursors["press"], "102")

    def test_a_restart_queues_nothing_twice(self) -> None:
        runner, database, _ = self.build("review", [post(101)])
        database.cursors["press"] = "100"
        runner.detect(runner.routes["press"])
        database.cursors["press"] = "100"
        again, _, _ = self.build("review", [post(101)], database)
        again.detect(again.routes["press"])
        self.assertEqual(len(database.items), 2)


class TestDelivery(ServiceFixture, unittest.TestCase):
    def queued(self, mode: str) -> tuple[service.Service, FakeStore, FakeOpenPost]:
        runner, database, client = self.build(mode, [post(101)])
        database.cursors["press"] = "100"
        runner.detect(runner.routes["press"])
        return runner, database, client

    def test_review_mode_creates_drafts_without_publishing(self) -> None:
        runner, database, client = self.queued("review")
        runner.deliver_due()
        self.assertEqual({row["state"] for row in database.items}, {"drafted"})
        self.assertEqual(client.published, [])
        self.assertEqual(
            client.created[0][2], store.idempotency_key(post(101).uri, "acc-x", 0)
        )
        self.assertEqual(
            client.metadata[0],
            {"crossposter_route": "press", "crossposter_source": post(101).url},
        )

    def test_auto_mode_publishes_and_the_x_text_carries_no_link(self) -> None:
        runner, database, client = self.queued("auto")
        runner.deliver_due()
        self.assertEqual({row["state"] for row in database.items}, {"submitted"})
        self.assertEqual(client.published, ["pub-1", "pub-2"])
        self.assertEqual(client.created[0][1], "Post 101")
        self.assertEqual(
            client.created[1][1], "Post 101\n\nhttps://microblog.example/@press/101"
        )

    def test_transient_errors_back_off_until_the_budget_is_spent(self) -> None:
        runner, database, client = self.queued("auto")
        client.failure = web.RequestError(
            "https://openpost/api/v1/publications", 503, {"Retry-After": "120"}, "busy"
        )
        runner.deliver_due()
        self.assertEqual({row["state"] for row in database.items}, {"pending"})
        self.assertGreaterEqual(database.items[0]["delay"], 120)
        runner.deliver_due()
        runner.deliver_due()
        self.assertEqual({row["state"] for row in database.items}, {"dead_lettered"})
        self.assertIn("HTTP 503", database.items[0]["last_error"])

    def test_a_retry_after_creation_reuses_the_publication(self) -> None:
        runner, database, client = self.queued("auto")
        client.publish_failure = web.RequestError(
            "https://openpost/api/v1/publications/pub-1/publish-now", 503, {}, "busy"
        )
        runner.deliver_due()
        self.assertEqual(
            [row["publication_id"] for row in database.items], ["pub-1", "pub-2"]
        )
        client.publish_failure = None
        runner.deliver_due()
        self.assertEqual({row["state"] for row in database.items}, {"submitted"})
        self.assertEqual(len(client.created), 2)
        self.assertEqual(client.published, ["pub-1", "pub-2"])

    def test_media_is_fetched_from_the_refreshed_source_post(self) -> None:
        runner, database, _ = self.build(
            "review", [picture(101, "https://microblog.example/m/original.jpg")]
        )
        database.cursors["press"] = "100"
        runner.detect(runner.routes["press"])
        runner.sources["press"].fresh_url = "https://microblog.example/m/optimised.jpg"
        fetched: list[str] = []

        def download(url: str, headers: dict, target: Path) -> Path:
            fetched.append(url)
            target.write_bytes(b"\xff\xd8 image")
            return target

        with patch.object(service.web, "download", download):
            runner.deliver_due()
        self.assertEqual(set(fetched), {"https://microblog.example/m/optimised.jpg"})
        self.assertEqual({row["state"] for row in database.items}, {"drafted"})

    def test_source_media_that_is_not_ready_is_retried(self) -> None:
        runner, database, _ = self.build(
            "review", [picture(101, "https://microblog.example/m/original.jpg")]
        )
        database.cursors["press"] = "100"
        runner.detect(runner.routes["press"])

        def download(url: str, headers: dict, target: Path) -> Path:
            raise web.RequestError(url, 403, {}, "no-preview")

        with patch.object(service.web, "download", download):
            runner.deliver_due()
        self.assertEqual({row["state"] for row in database.items}, {"pending"})
        self.assertIn("not available yet", database.items[0]["last_error"])

    def test_permanent_errors_dead_letter_at_once(self) -> None:
        runner, database, client = self.queued("auto")
        client.failure = web.RequestError(
            "https://openpost/api/v1/publications", 422, {}, "invalid"
        )
        runner.deliver_due()
        self.assertEqual({row["state"] for row in database.items}, {"dead_lettered"})


class TestFollowUp(ServiceFixture, unittest.TestCase):
    def submitted(self) -> tuple[service.Service, FakeStore, FakeOpenPost]:
        runner, database, client = self.build("auto", [post(101)])
        database.cursors["press"] = "100"
        runner.detect(runner.routes["press"])
        runner.deliver_due()
        return runner, database, client

    def test_published_destinations_close_the_item(self) -> None:
        runner, database, client = self.submitted()
        client.outcome = [{"status": "published"}]
        runner.follow()
        self.assertEqual({row["state"] for row in database.items}, {"published"})

    def test_failed_destinations_keep_the_provider_error(self) -> None:
        runner, database, client = self.submitted()
        client.outcome = [
            {
                "status": "failed",
                "error_retryable": False,
                "error_message": "rejected by X",
            }
        ]
        runner.follow()
        self.assertEqual({row["state"] for row in database.items}, {"failed"})
        self.assertEqual(database.items[0]["last_error"], "rejected by X")

    def test_a_provider_rejection_fails_without_a_resend(self) -> None:
        runner, database, client = self.submitted()
        client.outcome = [REJECTED]
        runner.follow()
        self.assertEqual({row["state"] for row in database.items}, {"failed"})
        self.assertEqual(
            database.items[0]["last_error"], "provider_rejected (HTTP 400)"
        )
        self.assertEqual(len(client.created), 2)

    def test_an_unavailable_provider_is_resent_under_a_new_key(self) -> None:
        runner, database, client = self.submitted()
        client.outcome = [UNAVAILABLE]
        runner.follow()
        self.assertEqual({row["state"] for row in database.items}, {"pending"})
        self.assertEqual(database.items[0]["resends"], 1)
        runner.deliver_due()
        self.assertEqual({row["state"] for row in database.items}, {"submitted"})
        self.assertEqual(
            client.created[2][2],
            store.idempotency_key(post(101).uri, "acc-x", 1),
        )
        self.assertEqual(client.published, ["pub-1", "pub-2", "pub-3", "pub-4"])
        client.outcome = [{"status": "published"}]
        runner.follow()
        self.assertEqual({row["state"] for row in database.items}, {"published"})

    def test_resends_dead_letter_once_the_attempts_are_spent(self) -> None:
        runner, database, client = self.submitted()
        client.outcome = [UNAVAILABLE]
        runner.follow()
        runner.deliver_due()
        runner.follow()
        self.assertEqual({row["state"] for row in database.items}, {"dead_lettered"})
        self.assertEqual(
            database.items[0]["last_error"], "manual_resolution (HTTP 503)"
        )

    def test_a_reviewed_draft_is_never_resent(self) -> None:
        runner, database, client = self.build("review", [post(101)])
        database.cursors["press"] = "100"
        runner.detect(runner.routes["press"])
        runner.deliver_due()
        client.outcome = [UNAVAILABLE]
        runner.follow()
        self.assertEqual({row["state"] for row in database.items}, {"failed"})
        self.assertEqual(len(client.created), 2)

    def test_failures_are_reported_once(self) -> None:
        runner, _, client = self.submitted()
        client.outcome = [
            {
                "status": "failed",
                "error_retryable": False,
                "error_message": "rejected by X",
            }
        ]
        runner.follow()
        sent: list[list[dict]] = []
        with patch.object(
            service.notify, "send", lambda mail, recipients, rows: sent.append(rows)
        ):
            runner.report()
            runner.report()
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(sent[0]), 2)
