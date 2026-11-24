from __future__ import annotations

import urllib.parse

from crossposter import web
from crossposter.sources import Media, SourceItem

PAGE_SIZE = 25
MAX_PAGES = 4
PUBLIC = 1
PUBLISHED = 1
VISIBILITY = {1: "public", 2: "unlisted", 3: "private", 4: "internal"}


def _files(detail: dict) -> list[dict]:
    files = list(detail.get("files") or [])
    for playlist in detail.get("streamingPlaylists") or []:
        files.extend(playlist.get("files") or [])
    return [
        item for item in files if item.get("fileDownloadUrl") or item.get("fileUrl")
    ]


def best_file(detail: dict) -> Media | None:
    files = _files(detail)
    if not files:
        return None
    chosen = max(
        files, key=lambda item: int((item.get("resolution") or {}).get("id") or 0)
    )
    return Media(
        url=str(chosen.get("fileDownloadUrl") or chosen.get("fileUrl")),
        mime="video/mp4",
        description="",
        size=int(chosen.get("size") or 0),
    )


def published_public(video: dict) -> bool:
    privacy = int((video.get("privacy") or {}).get("id") or 0)
    state = int((video.get("state") or {}).get("id") or PUBLISHED)
    return privacy == PUBLIC and state == PUBLISHED


def parse_video(video: dict, detail: dict) -> SourceItem:
    media = best_file(detail)
    return SourceItem(
        uri=str(video["url"]),
        url=str(video["url"]),
        platform="peertube",
        text=str(detail.get("description") or video.get("description") or ""),
        visibility=VISIBILITY.get(int((video.get("privacy") or {}).get("id") or 0), ""),
        tags=tuple(str(tag) for tag in detail.get("tags") or []),
        media=(media,) if media else (),
        in_reply_to="",
        reblog=False,
        spoiler="",
        application="",
        title=str(video.get("name") or ""),
        cursor=str(video.get("publishedAt") or ""),
    )


class PeerTubeSource:
    platform = "peertube"

    def __init__(self, base_url: str, account: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.channel = account
        self.headers = {"Authorization": f"Bearer {token}"}

    def _page(self, start: int) -> list[dict]:
        query = urllib.parse.urlencode(
            {"sort": "-publishedAt", "count": PAGE_SIZE, "start": start}
        )
        body = web.get_json(
            f"{self.base_url}/api/v1/video-channels/{self.channel}/videos?{query}",
            self.headers,
        )
        return list(body.get("data") or [])

    def _detail(self, video: dict) -> dict:
        return dict(
            web.get_json(f"{self.base_url}/api/v1/videos/{video['uuid']}", self.headers)
        )

    def refresh(self, item: SourceItem) -> SourceItem:
        return item

    def newest_cursor(self) -> str:
        page = self._page(0)
        return str(page[0].get("publishedAt") or "") if page else ""

    def fetch(self, cursor: str) -> list[SourceItem]:
        fresh: list[dict] = []
        for index in range(MAX_PAGES):
            page = self._page(index * PAGE_SIZE)
            newer = [
                video for video in page if str(video.get("publishedAt") or "") > cursor
            ]
            fresh.extend(newer)
            if len(newer) < len(page) or len(page) < PAGE_SIZE:
                break
        ordered = sorted(fresh, key=lambda video: str(video.get("publishedAt") or ""))
        return [
            parse_video(video, self._detail(video))
            for video in ordered
            if published_public(video)
        ]
