from __future__ import annotations

import mimetypes
import urllib.parse
from typing import ClassVar

from crossposter import adapt, web
from crossposter.sources import Media, SourceItem

PAGE_SIZE = 40
MAX_PAGES = 5
MEDIA_TYPES = {
    "image": "image/jpeg",
    "gifv": "video/mp4",
    "video": "video/mp4",
    "audio": "audio/mpeg",
}


def _mime(attachment: dict) -> str:
    guessed, _ = mimetypes.guess_type(
        urllib.parse.urlparse(str(attachment.get("url") or "")).path
    )
    return guessed or MEDIA_TYPES.get(
        str(attachment.get("type")), "application/octet-stream"
    )


def parse_status(status: dict, platform: str) -> SourceItem:
    application = status.get("application") or {}
    return SourceItem(
        uri=str(status["uri"]),
        url=str(status.get("url") or status["uri"]),
        platform=platform,
        text=adapt.html_to_text(str(status.get("content") or "")),
        visibility=str(status.get("visibility") or ""),
        tags=tuple(str(tag.get("name") or "") for tag in status.get("tags") or []),
        media=tuple(
            Media(
                url=str(attachment.get("url") or ""),
                mime=_mime(attachment),
                description=str(attachment.get("description") or ""),
                size=0,
            )
            for attachment in status.get("media_attachments") or []
        ),
        in_reply_to=str(status.get("in_reply_to_id") or ""),
        reblog=bool(status.get("reblog")),
        spoiler=str(status.get("spoiler_text") or ""),
        application=str(application.get("name") or ""),
        cursor=str(status["id"]),
    )


class MastodonSource:
    platform = "mastodon"
    filters: ClassVar[dict[str, str]] = {
        "exclude_replies": "true",
        "exclude_reblogs": "true",
    }

    def __init__(self, base_url: str, account: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.account = account
        self.headers = {"Authorization": f"Bearer {token}"}
        self._account_id = ""

    def _get(self, path: str, query: dict[str, str]) -> object:
        return web.get_json(
            f"{self.base_url}{path}?{urllib.parse.urlencode(query)}", self.headers
        )

    def account_id(self) -> str:
        if not self._account_id:
            found = self._get("/api/v1/accounts/lookup", {"acct": self.account})
            self._account_id = str(found["id"])
        return self._account_id

    def newest_cursor(self) -> str:
        statuses = self._get(
            f"/api/v1/accounts/{self.account_id()}/statuses", {"limit": "1"}
        )
        return str(statuses[0]["id"]) if statuses else "0"

    def refresh(self, item: SourceItem) -> SourceItem:
        status = self._get(f"/api/v1/statuses/{item.cursor}", {})
        return parse_status(dict(status), self.platform)

    def fetch(self, cursor: str) -> list[SourceItem]:
        items: list[SourceItem] = []
        for _ in range(MAX_PAGES):
            query = {"min_id": cursor, "limit": str(PAGE_SIZE), **self.filters}
            page = self._get(f"/api/v1/accounts/{self.account_id()}/statuses", query)
            if not page:
                break
            ordered = sorted(page, key=lambda status: int(status["id"]))
            items.extend(parse_status(status, self.platform) for status in ordered)
            cursor = str(ordered[-1]["id"])
            if len(page) < PAGE_SIZE:
                break
        return items
