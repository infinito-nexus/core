from __future__ import annotations

import logging
import mimetypes
import random
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from crossposter import adapt, notify, retry, store, web
from crossposter.sources.mastodon import MastodonSource
from crossposter.sources.peertube import PeerTubeSource
from crossposter.sources.pixelfed import PixelfedSource

if TYPE_CHECKING:
    from crossposter.config import Config, Route
    from crossposter.openpost import Destination, OpenPost
    from crossposter.sources import SourceItem

LOG = logging.getLogger("crossposter")
SOURCES = {
    "mastodon": MastodonSource,
    "pixelfed": PixelfedSource,
    "peertube": PeerTubeSource,
}
JPEG_QUALITY = 90
SOURCE_MEDIA_UNAVAILABLE = 503
MAX_JPEG_PIXELS_FOR_256M_MEM_LIMIT = 4096 * 4096


def _fits_memory(size: tuple[int, int], url: str) -> None:
    width, height = size
    if width * height > MAX_JPEG_PIXELS_FOR_256M_MEM_LIMIT:
        raise web.RefusedError(
            url,
            f"{width}x{height} pixels exceed {MAX_JPEG_PIXELS_FOR_256M_MEM_LIMIT}",
        )


def to_jpeg(source: Path, url: str) -> Path:
    from PIL import Image

    target = source.with_suffix(".jpg")
    try:
        with Image.open(source) as image:
            _fits_memory(image.size, url)
            image.convert("RGB").save(target, "JPEG", quality=JPEG_QUALITY)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        raise web.RefusedError(
            url, f"the source media is no convertible image: {error}"
        ) from error
    return target


def credentials_for(source_url: str, media_url: str, headers: dict) -> dict:
    same_origin = web.origin(source_url) == web.origin(media_url)
    return dict(headers) if same_origin else {}


def failure(rendition: dict) -> str:
    delivery = rendition.get("delivery") or {}
    reason = (
        rendition.get("error_message")
        or delivery.get("terminal_reason")
        or delivery.get("recovery_action")
        or "delivery failed"
    )
    status = rendition.get("error_http_status")
    return f"{reason} (HTTP {status})" if status else str(reason)


def resendable_failure(rendition: dict) -> bool:
    if (rendition.get("delivery") or {}).get("recovery_action") == "manual_resolution":
        return True
    status = rendition.get("error_http_status")
    return status is not None and retry.transient(int(status))


class Service:
    def __init__(
        self, config: Config, database: store.Store, openpost: OpenPost
    ) -> None:
        self.config = config
        self.store = database
        self.openpost = openpost
        self.routes = {route.name: route for route in config.routes}
        self.sources = {
            route.name: SOURCES[route.source.platform](
                route.source.base_url, route.source.account, route.source.token
            )
            for route in config.routes
        }
        self.rng = random.SystemRandom()

    def heartbeat(self, state: str) -> None:
        Path(self.config.heartbeat_file).write_text(f"{time.time():.0f} {state}\n")

    def run_forever(self) -> None:
        self.store.migrate()
        while not self.store.lock():
            LOG.info("another crossposter holds the lock; standing by")
            self.heartbeat("standby")
            time.sleep(self.config.poll_interval_seconds)
        LOG.info("lock acquired; polling %d route(s)", len(self.routes))
        while True:
            self.tick()
            self.heartbeat("active")
            time.sleep(self.config.poll_interval_seconds)

    def tick(self) -> None:
        for route in self.routes.values():
            self.detect(route)
        self.deliver_due()
        self.follow()
        self.report()

    def detect(self, route: Route) -> None:
        source = self.sources[route.name]
        try:
            cursor = self.store.cursor(route.name)
            if cursor is None:
                self.store.advance(route.name, source.newest_cursor(), [])
                LOG.info(
                    "route %s activated; existing posts are not forwarded", route.name
                )
                return
            items = source.fetch(cursor)
            destinations = self.openpost.destinations(route.targets)
        except web.RequestError as error:
            LOG.warning(
                "route %s: polling failed, retrying next interval: %s",
                route.name,
                error,
            )
            return
        enqueued = [
            (item, destination.account_id, destination.platform)
            for item in items
            if not self._refused(route, item)
            for destination in destinations
            if not self._plan(route, item, destination).skip
        ]
        self.store.advance(route.name, items[-1].cursor if items else cursor, enqueued)
        if enqueued:
            LOG.info("route %s: queued %d delivery(ies)", route.name, len(enqueued))

    def _refused(self, route: Route, item: SourceItem) -> bool:
        reason = route.refusal(item, self.config.opt_out_tag)
        if reason:
            LOG.info("route %s: %s not forwarded (%s)", route.name, item.url, reason)
        return bool(reason)

    @staticmethod
    def _plan(route: Route, item: SourceItem, destination: Destination) -> adapt.Plan:
        return adapt.prepare(
            item, destination.platform, route.template(destination.platform), route.mode
        )

    def _destination(self, route: Route, account_id: str) -> Destination:
        for destination in self.openpost.destinations(route.targets):
            if destination.account_id == account_id:
                return destination
        raise web.RequestError(account_id, 404, {}, "the target account left the route")

    def _media(
        self, route: Route, plan: adapt.Plan, folder: Path
    ) -> list[tuple[str, str]]:
        uploaded = []
        headers = self.sources[route.name].headers
        for index, attachment in enumerate(plan.media):
            web.require_fetchable(attachment.media.url)
            suffix = mimetypes.guess_extension(attachment.media.mime) or ""
            try:
                local = web.download(
                    attachment.media.url,
                    credentials_for(
                        route.source.base_url, attachment.media.url, headers
                    ),
                    folder / f"media-{index}{suffix}",
                )
            except web.RefusedError:
                raise
            except web.RequestError as error:
                raise web.RequestError(
                    attachment.media.url,
                    SOURCE_MEDIA_UNAVAILABLE,
                    error.headers,
                    f"the source media is not available yet: {error}",
                ) from error
            mime = attachment.media.mime
            if attachment.jpeg and mime != "image/jpeg":
                local, mime = to_jpeg(local, attachment.media.url), "image/jpeg"
            uploaded.append(
                (self.openpost.upload(local, local.name, mime), attachment.alt_text)
            )
        return uploaded

    def deliver_due(self) -> None:
        for row in self.store.due():
            self.deliver(row)

    def deliver(self, row: dict) -> None:
        route = self.routes.get(row["route"])
        attempts = int(row["attempts"]) + 1
        if route is None:
            state = store.transition("pending", "permanent")
            self.store.update(
                row["id"],
                state,
                str(row["publication_id"]),
                attempts,
                "the route was removed",
                0,
            )
            return
        item = store.item_from_json(row["payload"])
        publication_id = str(row["publication_id"])
        try:
            if item.media and not publication_id:
                item = self.sources[route.name].refresh(item)
            destination = self._destination(route, row["target"])
            plan = self._plan(route, item, destination)
            if publication_id:
                publication = self.openpost.publication(publication_id)
            else:
                key = store.idempotency_key(
                    item.uri, destination.account_id, int(row["resends"])
                )
                with tempfile.TemporaryDirectory(prefix="crossposter-") as folder:
                    media = self._media(route, plan, Path(folder))
                publication = self.openpost.create(
                    destination,
                    plan.title,
                    plan.text,
                    plan.profile,
                    media,
                    key,
                    {"crossposter_route": route.name, "crossposter_source": item.url},
                )
                publication_id = str(publication["id"])
            if plan.draft_only:
                state = store.transition("pending", "drafted")
            else:
                if str(publication.get("status")) == "draft":
                    if plan.media:
                        self.openpost.await_media(publication_id)
                    self.openpost.publish_now(publication)
                state = store.transition("pending", "submitted")
            self.store.update(row["id"], state, publication_id, attempts, "", 0)
            LOG.info(
                "%s -> %s %s: %s",
                item.url,
                destination.platform,
                destination.slug,
                state,
            )
        except web.RequestError as error:
            event = "transient" if error.transient else "permanent"
            state = store.transition(
                "pending", event, attempts, self.config.retry.max_attempts
            )
            pause = retry.delay(
                attempts,
                error.headers,
                time.time(),
                self.config.retry.base_seconds,
                self.config.retry.cap_seconds,
                self.rng,
            )
            self.store.update(
                row["id"],
                state,
                publication_id,
                attempts,
                str(error),
                pause,
            )
            LOG.warning(
                "%s -> %s: %s (%s, attempt %d)",
                item.url,
                row["target"],
                state,
                error,
                attempts,
            )

    def follow(self) -> None:
        for row in self.store.open_publications():
            try:
                renditions = self.openpost.renditions(str(row["publication_id"]))
            except web.RequestError as error:
                LOG.warning(
                    "publication %s: status unavailable: %s",
                    row["publication_id"],
                    error,
                )
                continue
            states = {str(rendition.get("status")) for rendition in renditions}
            failed = [
                rendition
                for rendition in renditions
                if rendition.get("status") == "failed"
                and not rendition.get("error_retryable")
            ]
            if failed:
                self._failed(row, failed)
            elif renditions and states == {"published"}:
                state = store.transition(str(row["state"]), "delivered")
                self.store.update(
                    row["id"],
                    state,
                    str(row["publication_id"]),
                    int(row["attempts"]),
                    "",
                    0,
                )

    def _failed(self, row: dict, failed: list[dict]) -> None:
        detail = "; ".join(failure(rendition) for rendition in failed)
        attempts = int(row["attempts"]) + 1
        resendable = row["state"] == "submitted" and all(
            resendable_failure(rendition) for rendition in failed
        )
        if not resendable:
            event = "delivery_failed"
        elif attempts >= self.config.retry.max_attempts:
            event = "exhausted"
        else:
            pause = retry.delay(
                attempts,
                {},
                time.time(),
                self.config.retry.base_seconds,
                self.config.retry.cap_seconds,
                self.rng,
            )
            self.store.resend(row["id"], attempts, detail, pause)
            LOG.warning(
                "publication %s failed transiently, resending in %.0fs: %s",
                row["publication_id"],
                pause,
                detail,
            )
            return
        state = store.transition(str(row["state"]), event)
        self.store.update(
            row["id"], state, str(row["publication_id"]), attempts, detail, 0
        )

    def report(self) -> None:
        rows = self.store.unnotified()
        if not rows:
            return
        if self.config.mail and self.config.recipients:
            try:
                notify.send(self.config.mail, self.config.recipients, rows)
            except OSError as error:
                LOG.warning("notification failed, retrying next interval: %s", error)
                return
        for row in rows:
            self.store.mark_notified(row["id"])
