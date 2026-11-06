from __future__ import annotations

import json
import re
import urllib.parse

from openpost.api import anonymous_jpeg, check

X_LIMIT = 280
FACEBOOK_PAGES = ("424242", "525252")


def hits(journal: list[dict], method: str, path: str, tag: str) -> list[dict]:
    found = []
    for entry in journal:
        request = entry["request"]
        text = urllib.parse.unquote_plus(
            str(request.get("url")) + " " + str(request.get("body") or "")
        )
        if (
            request["method"] == method
            and re.fullmatch(path, str(request["url"]).split("?")[0])
            and tag in text
        ):
            found.append(entry)
    return sorted(found, key=lambda entry: entry["request"]["loggedDate"])


def statuses(entries: list[dict]) -> list[int]:
    return [int(entry["responseDefinition"]["status"]) for entry in entries]


def form_value(entry: dict, key: str) -> str:
    request = entry["request"]
    fields = urllib.parse.parse_qs(urllib.parse.urlparse(str(request["url"])).query)
    body = str(request.get("body") or "")
    if body.startswith("{"):
        value = json.loads(body).get(key)
        return str(value) if value else ""
    fields.update(urllib.parse.parse_qs(body))
    return fields.get(key, [""])[0]


def check_journal(journal: list[dict], label: str, tag: str) -> None:
    if label in ("x", "scheduled", "member"):
        posts = hits(journal, "POST", "/2/tweets", tag)
        check(
            f"X receives the {label} post exactly once",
            statuses(posts) == [201],
            statuses(posts),
        )
        if label == "x":
            text = (
                str(json.loads(posts[0]["request"]["body"]).get("text"))
                if posts
                else ""
            )
            check(
                f"the X post stays within {X_LIMIT} characters",
                0 < len(text) <= X_LIMIT,
                len(text),
            )
    elif label in ("x-429", "x-503"):
        posts = statuses(hits(journal, "POST", "/2/tweets", tag))
        wanted = [int(label[2:]), 201]
        check(
            f"X answers {wanted[0]} once and then receives exactly one post",
            posts == wanted,
            posts,
        )
    elif label == "x-400":
        posts = statuses(hits(journal, "POST", "/2/tweets", tag))
        check(
            "X rejects the post and its single retry, and nothing else is sent",
            posts == [400, 400],
            posts,
        )
    elif label == "facebook":
        for page in FACEBOOK_PAGES:
            posts = statuses(hits(journal, "POST", rf"/v[0-9.]+/{page}/feed", tag))
            check(
                f"Facebook Page {page} receives exactly one feed post",
                posts == [200],
                posts,
            )
    elif label == "instagram":
        containers = hits(journal, "POST", r"/v[0-9.]+/17841400000000000/media", tag)
        published = hits(
            journal, "POST", r"/v[0-9.]+/17841400000000000/media_publish", ""
        )
        image = form_value(containers[0], "image_url") if containers else ""
        check(
            "Instagram receives one media container",
            statuses(containers) == [200],
            statuses(containers),
        )
        check(
            "Instagram receives a publish call after the container",
            bool(
                containers
                and published
                and published[-1]["request"]["loggedDate"]
                >= containers[0]["request"]["loggedDate"]
            ),
        )
        check(
            "the Instagram container carries a public JPEG URL",
            image.startswith("https://") and anonymous_jpeg(image),
            image,
        )
    elif label == "youtube":
        sessions = [
            entry
            for entry in hits(journal, "POST", "/upload/youtube/v3/videos", tag)
            if "uploadType=resumable" in entry["request"]["url"]
        ]
        uploads = hits(
            journal, "PUT", "/upload/youtube/v3/videos", "upload_id=simulator-upload"
        )
        check(
            "YouTube receives one resumable upload session",
            statuses(sessions) == [200],
            statuses(sessions),
        )
        check(
            "YouTube receives the video on the resumable upload URL",
            bool(uploads),
            statuses(uploads),
        )
    elif label == "tiktok":
        inits = statuses(hits(journal, "POST", "/v2/post/publish/content/init/", tag))
        polls = hits(journal, "POST", "/v2/post/publish/status/fetch/", "")
        check("TikTok receives exactly one photo post init", inits == [200], inits)
        check("OpenPost polls the TikTok publish status", bool(polls))
