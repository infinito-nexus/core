"""Every invokable role's ``video`` addresses one reachable, embeddable video.

The root-README overview renders a Video link per role, and a reader following
it expects a demo rather than a directory. A channel, a playlist or a product
page cannot be embedded, so a page that merely contains videos does not satisfy
the column even though it resolves.

Accepted shapes:
  YouTube   watch?v=, youtu.be/, /embed/ (also youtube-nocookie.com)
  PeerTube  /w/<id> or /videos/watch/<uuid> on any instance, since PeerTube is
            federated and the host cannot be enumerated
  Vimeo     vimeo.com/<id>

A role whose upstream publishes no single embeddable video opts out with

    # nocheck: info-video-embed <reason>

in the first 30 lines of ``meta/info.yml``, the same place and mechanism the
``info-media`` marker uses, so an exemption sits beside the ``video`` field it
speaks about.

This is an external test because reachability needs live HTTP. Like its
siblings it never fails on an unanswered probe: a timeout or connection error
is reported as unverified, so a firewalled or geo-blocked runner cannot turn a
good URL red. A shape that cannot be embedded is a repository fact rather than
a network one, so that half is asserted.
"""

from __future__ import annotations

import concurrent.futures
import re
import unittest

import requests

from utils.annotations.message import warning
from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_INFO
from utils.roles.validation.invokable import _get_invokable_paths, _is_role_invokable

from . import PROJECT_ROOT

_RULE = "info-video-embed"
_USER_AGENT = "infinito-nexus-video-check"
_TIMEOUT_SECONDS = 15
_MAX_WORKERS = 8

_EMBEDDABLE = re.compile(
    r"^https://(?:"
    r"(?:www\.)?youtube(?:-nocookie)?\.com/(?:watch\?(?:[^#]*&)?v=|embed/)[\w-]{6,}"
    r"|youtu\.be/[\w-]{6,}"
    r"|(?:www\.)?vimeo\.com/\d{6,}"
    r"|[\w.-]+/(?:w/[\w-]{6,}|videos/(?:watch|embed)/[0-9a-fA-F-]{36})"
    r")",
)


def _video_of(role: str) -> str:
    path = PROJECT_ROOT / "roles" / role / ROLE_FILE_META_INFO
    if not path.is_file():
        return ""
    data = load_yaml_any(str(path)) or {}
    value = data.get("video") if isinstance(data, dict) else None
    return value.strip() if isinstance(value, str) else ""


def _candidates() -> list[tuple[str, str]]:
    """Return (role, video url) for every invokable role that has not opted out."""
    invokable = _get_invokable_paths()
    found: list[tuple[str, str]] = []
    for role_dir in sorted((PROJECT_ROOT / "roles").iterdir()):
        if not role_dir.is_dir() or not _is_role_invokable(role_dir.name, invokable):
            continue
        info_path = role_dir / ROLE_FILE_META_INFO
        if info_path.is_file() and is_suppressed_in_head(
            read_text(str(info_path)).splitlines(), _RULE
        ):
            continue
        video = _video_of(role_dir.name)
        if video:
            found.append((role_dir.name, video))
    return found


def _probe_target(url: str) -> tuple[str, dict[str, str]]:
    """Return the URL to probe and its query for ``url``.

    YouTube answers a removed or private video with HTTP 200 and a "Video
    unavailable" page, so a plain fetch proves only that YouTube is up. Its
    oEmbed endpoint answers 400 for the same video, which is the difference
    this check needs.
    """
    if re.match(r"^https://(?:(?:www\.)?youtube|youtu)\.", url):
        # nocheck: url  answers 404 without the query this call always supplies
        return "https://www.youtube.com/oembed", {"url": url, "format": "json"}
    return url, {}


def _probe(url: str) -> tuple[str, str]:
    """Return (kind, detail) with kind one of ok, warn, unverified."""
    target, params = _probe_target(url)
    try:
        response = requests.get(
            target,
            params=params,
            allow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
            stream=True,
            timeout=_TIMEOUT_SECONDS,
        )
        try:
            status = response.status_code
        finally:
            response.close()
    except requests.Timeout as exc:
        return "unverified", f"Timeout: {exc}"
    except requests.RequestException as exc:
        return "unverified", f"{type(exc).__name__}: {exc}"

    if status < 400 or status in (401, 403, 405, 406, 415, 429):
        return "ok", f"HTTP {status}"
    return "warn", f"HTTP {status}"


class TestInfoVideoEmbeddable(unittest.TestCase):
    def test_invokable_role_videos_are_embeddable_and_reachable(self) -> None:
        candidates = _candidates()
        self.assertTrue(candidates, "No invokable role declares a video")

        not_embeddable = [
            (role, url) for role, url in candidates if not _EMBEDDABLE.match(url)
        ]
        for role, url in not_embeddable:
            warning(
                f"{role}: {url} addresses a channel, playlist or page rather than "
                f"one embeddable video",
                title="Video not embeddable",
                file=f"roles/{role}/{ROLE_FILE_META_INFO}",
            )

        embeddable = [pair for pair in candidates if pair not in not_embeddable]
        with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            results = list(pool.map(lambda pair: _probe(pair[1]), embeddable))

        for (role, url), (kind, detail) in zip(embeddable, results, strict=True):
            if kind == "ok":
                continue
            warning(
                f"{role}: {url} answered {detail}"
                if kind == "warn"
                else f"{role}: {url} was not checked ({detail})",
                title="Video unreachable" if kind == "warn" else "Video unverified",
                file=f"roles/{role}/{ROLE_FILE_META_INFO}",
            )

        self.assertFalse(
            not_embeddable,
            f"{len(not_embeddable)} invokable role(s) point 'video' at something "
            f"that cannot be embedded. Replace it with a single video URL, or opt "
            f"the role out with '# nocheck: {_RULE} <reason>' in the first 30 "
            f"lines of {ROLE_FILE_META_INFO}:\n"
            + "\n".join(f"  {role}: {url}" for role, url in not_embeddable),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
