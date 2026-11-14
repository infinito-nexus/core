from __future__ import annotations

import json
import time
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING

from crossposter import web

if TYPE_CHECKING:
    from pathlib import Path

    from crossposter.config import Targets


PUBLIC_MEDIA_POLLS = 24
PUBLIC_MEDIA_POLL_SECONDS = 5
ANALYSED = ("ready", "failed")


def publishable(medium: dict) -> bool:
    public = bool(
        medium.get("public_url_checked_at") and medium.get("public_url_ready")
    )
    analysed = not str(medium.get("mime_type") or "").startswith("video/") or (
        medium.get("analysis_status") in ANALYSED
    )
    return public and analysed


@dataclass(frozen=True)
class Destination:
    account_id: str
    slug: str
    platform: str
    settings: dict


class TargetError(ValueError):
    pass


class OpenPost:
    def __init__(self, base_url: str, host: str, token: str, workspace: str) -> None:
        self.base_url = base_url.rstrip("/") + "/api/v1"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Host": host,
            "X-Forwarded-Proto": "https",
            "Content-Type": "application/json",
        }
        self.workspace = workspace

    def _call(
        self, method: str, path: str, body: object, key: str, accepted: tuple[int, ...]
    ) -> object:
        headers = {**self.headers, **({"Idempotency-Key": key} if key else {})}
        data = json.dumps(body).encode() if body is not None else None
        return web.request(method, self.base_url + path, headers, data, accepted).json()

    def get(self, path: str) -> object:
        return self._call("GET", path, None, "", (200,))

    def destinations(self, targets: Targets) -> list[Destination]:
        accounts = {
            str(item["id"]): item
            for item in self.get(f"/accounts?workspace_id={self.workspace}") or []
        }
        if targets.social_set:
            sets = self.get(f"/social-sets?workspace_id={self.workspace}") or []
            chosen = [item for item in sets if item.get("name") == targets.social_set]
            if not chosen:
                raise TargetError(f"social set {targets.social_set!r} does not exist")
            return [
                Destination(
                    account_id=str(entry["social_account_id"]),
                    slug=str(
                        accounts.get(str(entry["social_account_id"]), {}).get("slug")
                        or ""
                    ),
                    platform=str(entry["platform"]),
                    settings=dict(entry.get("default_settings") or {}),
                )
                for entry in chosen[0].get("accounts") or []
            ]
        by_slug = {str(item.get("slug")): item for item in accounts.values()}
        missing = [slug for slug in targets.accounts if slug not in by_slug]
        if missing:
            raise TargetError(f"accounts {missing} are not connected in the workspace")
        return [
            Destination(
                str(by_slug[slug]["id"]), slug, str(by_slug[slug]["platform"]), {}
            )
            for slug in targets.accounts
        ]

    def upload(self, source: Path, filename: str, mime: str) -> str:
        session = self._call(
            "POST",
            "/media/upload-session",
            {
                "workspace_id": self.workspace,
                "filename": filename,
                "mime_type": mime,
                "size": source.stat().st_size,
            },
            "",
            (200, 201),
        )
        target = session["upload"]
        url = urllib.parse.urlparse(str(target["url"]))
        headers = {
            name: str(value) for name, value in (target.get("headers") or {}).items()
        }
        if url.netloc in ("", self.headers["Host"]):
            headers.update(
                {
                    key: value
                    for key, value in self.headers.items()
                    if key != "Content-Type"
                }
            )
            url = urllib.parse.urlparse(
                self.base_url.rsplit("/api/v1", 1)[0]
                + url.path
                + (f"?{url.query}" if url.query else "")
            )
        web.upload(
            str(target["method"]), url.geturl(), headers, source, (200, 201, 204)
        )
        complete = urllib.parse.urlparse(str(session["complete_url"])).path.split(
            "/api/v1", 1
        )[1]
        completed = self._call(
            "POST", complete, {"workspace_id": self.workspace}, "", (200, 201)
        )
        return str(completed["id"])

    def create(
        self,
        destination: Destination,
        title: str,
        text: str,
        profile: str,
        media: list[tuple[str, str]],
        key: str,
        metadata: dict[str, str],
    ) -> dict:
        payload = {
            "workspace_id": self.workspace,
            "metadata": metadata,
            "title": title,
            "content_profile": profile,
            "source_text": text,
            "social_account_ids": [destination.account_id],
            "renditions": [
                {
                    "social_account_id": destination.account_id,
                    "settings": destination.settings,
                }
            ],
            "media": [
                {"media_id": media_id, "alt_text": alt} for media_id, alt in media
            ],
        }
        return dict(self._call("POST", "/publications", payload, key, (200, 201)))

    def publication(self, publication_id: str) -> dict:
        return dict(self.get(f"/publications/{publication_id}") or {})

    def await_media(self, publication_id: str) -> None:
        for _ in range(PUBLIC_MEDIA_POLLS):
            self._call(
                "POST", f"/publications/{publication_id}/validate", None, "", (200,)
            )
            media = self.publication(publication_id).get("media")
            if all(publishable(item) for item in media or []):
                return
            time.sleep(PUBLIC_MEDIA_POLL_SECONDS)
        raise web.RequestError(
            f"{self.base_url}/publications/{publication_id}",
            503,
            {},
            "OpenPost has not confirmed the public media URLs or video analysis yet",
        )

    def publish_now(self, publication: dict) -> None:
        self._call(
            "POST",
            f"/publications/{publication['id']}/publish-now",
            {"expected_revision": publication["revision"]},
            "",
            (200, 201, 202),
        )

    def renditions(self, publication_id: str) -> list[dict]:
        return list(self.publication(publication_id).get("renditions") or [])
