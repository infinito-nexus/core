from __future__ import annotations

import contextlib
import json
import re
import unittest
import unittest.mock
from pathlib import Path

from crossposter import store
from crossposter.sources import Media, SourceItem

from utils.cache.files import iter_project_files

from . import PROJECT_ROOT

SOURCE = "https://microblog.example/users/press/statuses/1"
SQL_SOURCE = PROJECT_ROOT / "roles/web-app-openpost/files/sql/crossposter"
PLACEHOLDER = re.compile(r"%\((\w+)\)s")
ITEM = SourceItem(
    uri=SOURCE,
    url="https://microblog.example/@press/1",
    platform="mastodon",
    text="Hello",
    visibility="public",
    tags=("news",),
    media=(
        Media(
            url="https://microblog.example/a.png",
            mime="image/png",
            description="alt",
            size=12,
        ),
    ),
    in_reply_to="",
    reblog=False,
    spoiler="",
    application="",
    cursor="1",
)


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | None]] = []

    def execute(self, text: str, parameters: dict | None = None) -> _Connection:
        self.calls.append((text, parameters))
        return self

    def fetchone(self) -> dict:
        return {"held": True, "cursor": "1"}

    def fetchall(self) -> list[dict]:
        return []

    def transaction(self) -> contextlib.nullcontext:
        return contextlib.nullcontext()


class TestPayload(unittest.TestCase):
    def test_a_stored_item_comes_back_unchanged(self) -> None:
        self.assertEqual(
            store.item_from_json(json.loads(store.item_to_json(ITEM))), ITEM
        )


class TestQueries(unittest.TestCase):
    def setUp(self) -> None:
        patcher = unittest.mock.patch.object(store, "SQL_DIR", SQL_SOURCE)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_query_has_one_file_and_every_file_a_query(self) -> None:
        statements = (Path(path) for path in iter_project_files(extensions=(".sql",)))
        self.assertEqual(
            sorted(
                path.relative_to(SQL_SOURCE).with_suffix("").as_posix()
                for path in statements
                if path.is_relative_to(SQL_SOURCE)
            ),
            sorted(store.QUERIES),
        )

    def test_an_unknown_query_is_refused(self) -> None:
        with self.assertRaises(KeyError):
            store.query("select_items; DROP SCHEMA crossposter")

    def test_every_call_binds_exactly_the_placeholders_of_its_statement(
        self,
    ) -> None:
        connection = _Connection()
        crossposter_store = store.Store.__new__(store.Store)
        crossposter_store.connection = connection

        crossposter_store.migrate()
        crossposter_store.lock()
        crossposter_store.cursor("press")
        crossposter_store.advance("press", "2", [(ITEM, "x-press", "x")])
        crossposter_store.due()
        crossposter_store.open_publications()
        crossposter_store.unnotified()
        crossposter_store.everything()
        crossposter_store.update(1, "drafted", "pub-1", 1, "", 0)
        crossposter_store.resend(1, 0, "HTTP 503", 30)
        crossposter_store.mark_notified(1)

        self.assertEqual(
            sorted(text for text, _ in connection.calls),
            sorted(store.query(name) for name in store.QUERIES),
        )
        for text, parameters in connection.calls:
            with self.subTest(statement=text.splitlines()[0]):
                self.assertEqual(set(PLACEHOLDER.findall(text)), set(parameters or {}))


class TestIdempotencyKey(unittest.TestCase):
    def test_the_key_is_stable_for_one_pair(self) -> None:
        self.assertEqual(
            store.idempotency_key(SOURCE, "account-1", 0),
            store.idempotency_key(SOURCE, "account-1", 0),
        )

    def test_the_key_differs_per_target_and_per_source(self) -> None:
        keys = {
            store.idempotency_key(SOURCE, "account-1", 0),
            store.idempotency_key(SOURCE, "account-2", 0),
            store.idempotency_key(SOURCE + "0", "account-1", 0),
        }
        self.assertEqual(len(keys), 3)

    def test_the_key_cannot_collide_through_concatenation(self) -> None:
        self.assertNotEqual(
            store.idempotency_key("ab", "c", 0), store.idempotency_key("a", "bc", 0)
        )

    def test_the_key_fits_an_http_header(self) -> None:
        key = store.idempotency_key(SOURCE, "account-1", 0)
        self.assertRegex(key, r"^crossposter-[0-9a-f]{64}$")

    def test_every_resend_gets_its_own_key_of_the_same_pair(self) -> None:
        first = store.idempotency_key(SOURCE, "account-1", 0)
        resent = store.idempotency_key(SOURCE, "account-1", 1)
        self.assertEqual(resent, f"{first}-r1")
        self.assertNotEqual(resent, store.idempotency_key(SOURCE, "account-1", 2))


class TestTransitions(unittest.TestCase):
    def test_review_mode_drafts(self) -> None:
        self.assertEqual(store.transition("pending", "drafted"), "drafted")

    def test_auto_mode_submits_then_publishes(self) -> None:
        self.assertEqual(store.transition("pending", "submitted"), "submitted")
        self.assertEqual(store.transition("submitted", "delivered"), "published")

    def test_a_draft_published_in_the_desk_becomes_published(self) -> None:
        self.assertEqual(store.transition("drafted", "delivered"), "published")

    def test_a_reported_delivery_failure_is_failed(self) -> None:
        self.assertEqual(store.transition("submitted", "delivery_failed"), "failed")
        self.assertEqual(store.transition("drafted", "delivery_failed"), "failed")

    def test_transient_errors_stay_pending_until_the_budget_is_spent(self) -> None:
        self.assertEqual(
            store.transition("pending", "transient", attempts=3, max_attempts=8),
            "pending",
        )
        self.assertEqual(
            store.transition("pending", "transient", attempts=8, max_attempts=8),
            "dead_lettered",
        )

    def test_a_submitted_item_can_be_resent_or_exhausted(self) -> None:
        self.assertEqual(store.transition("submitted", "resend"), "pending")
        self.assertEqual(store.transition("submitted", "exhausted"), "dead_lettered")

    def test_a_reviewed_draft_is_never_resent(self) -> None:
        with self.assertRaises(store.InvalidTransitionError):
            store.transition("drafted", "resend")

    def test_permanent_errors_dead_letter_at_once(self) -> None:
        self.assertEqual(store.transition("pending", "permanent"), "dead_lettered")

    def test_terminal_states_do_not_move(self) -> None:
        for state in ("published", "dead_lettered"):
            with self.assertRaises(store.InvalidTransitionError):
                store.transition(state, "submitted")

    def test_unknown_events_are_refused(self) -> None:
        with self.assertRaises(store.InvalidTransitionError):
            store.transition("pending", "teleported")

    def test_every_state_is_listed(self) -> None:
        self.assertEqual(
            set(store.STATES),
            {"pending", "drafted", "submitted", "published", "failed", "dead_lettered"},
        )
