from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crossposter.sources import Media, SourceItem

FEDIVERSE = frozenset({"mastodon", "pixelfed", "peertube"})
URL_WEIGHT = 23
ELLIPSIS = "…"

URL_RE = re.compile(r"https?://[^\s<>\"']+")
MENTION_RE = re.compile(
    r"(?<![\w@])@([A-Za-z0-9_][A-Za-z0-9_.-]*)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)"
)
HASHTAG_RE = re.compile(r"(?<![\w#])#\w+")


@dataclass(frozen=True)
class Limit:
    characters: int
    counter: str
    hashtags: int = 0


LIMITS = {
    "mastodon": Limit(500, "mastodon"),
    "pixelfed": Limit(500, "graphemes"),
    "peertube": Limit(10000, "graphemes"),
    "bluesky": Limit(300, "graphemes"),
    "x": Limit(280, "x"),
    "threads": Limit(500, "graphemes"),
    "facebook": Limit(63206, "graphemes"),
    "instagram": Limit(2200, "graphemes", hashtags=30),
    "linkedin": Limit(3000, "graphemes"),
    "youtube": Limit(5000, "graphemes"),
    "tiktok": Limit(2200, "graphemes"),
}

_X_SINGLE = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))
_ZWJ = "‍"


def _joins(previous: str, char: str) -> bool:
    code = ord(char)
    return (
        unicodedata.combining(char) > 0
        or 0xFE00 <= code <= 0xFE0F
        or 0x1F3FB <= code <= 0x1F3FF
        or 0xE0020 <= code <= 0xE007F
        or char == _ZWJ
        or previous.endswith(_ZWJ)
    )


def graphemes(text: str) -> list[str]:
    clusters: list[str] = []
    for char in text:
        if (clusters and _joins(clusters[-1], char)) or (
            clusters and _regional_pair(clusters[-1], char)
        ):
            clusters[-1] += char
        else:
            clusters.append(char)
    return clusters


def _regional(char: str) -> bool:
    return 0x1F1E6 <= ord(char) <= 0x1F1FF


def _regional_pair(cluster: str, char: str) -> bool:
    return len(cluster) == 1 and _regional(cluster) and _regional(char)


def _emoji(cluster: str) -> bool:
    return any(
        ord(char) >= 0x1F000 or 0x2600 <= ord(char) <= 0x27BF or char in (_ZWJ, "️")
        for char in cluster
    )


def _x_weight(cluster: str) -> int:
    if _emoji(cluster):
        return 2
    code = ord(cluster[0])
    return 1 if any(low <= code <= high for low, high in _X_SINGLE) else 2


def _split_urls(text: str) -> tuple[str, int]:
    urls = URL_RE.findall(text)
    return URL_RE.sub("", text), len(urls)


def count(text: str, network: str, spoiler: str = "") -> int:
    limit = LIMITS[network]
    if limit.counter == "mastodon":
        stripped, urls = _split_urls(MENTION_RE.sub(r"@\1", spoiler + text))
        return len(graphemes(stripped)) + urls * URL_WEIGHT
    if limit.counter == "x":
        stripped, urls = _split_urls(text)
        return (
            sum(_x_weight(cluster) for cluster in graphemes(stripped))
            + urls * URL_WEIGHT
        )
    return len(graphemes(text))


def fits(text: str, network: str, spoiler: str = "") -> bool:
    limit = LIMITS[network]
    if limit.hashtags and len(HASHTAG_RE.findall(text)) > limit.hashtags:
        return False
    return count(text, network, spoiler) <= limit.characters


def _drop_excess_hashtags(text: str, allowed: int) -> str:
    seen = 0

    def keep(match: re.Match[str]) -> str:
        nonlocal seen
        seen += 1
        return match.group(0) if seen <= allowed else ""

    return re.sub(r"[ \t]{2,}", " ", HASHTAG_RE.sub(keep, text)).strip()


def shorten(text: str, network: str, reserve: int = 0) -> str:
    limit = LIMITS[network]
    if limit.hashtags:
        text = _drop_excess_hashtags(text, limit.hashtags)
    budget = limit.characters - reserve
    if count(text, network) <= budget:
        return text
    tokens = re.findall(r"\S+|\s+", text)
    while tokens:
        candidate = "".join(tokens).rstrip() + ELLIPSIS
        if count(candidate, network) <= budget:
            return candidate
        tokens.pop()
    return ELLIPSIS


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._link: dict[str, str] | None = None
        self._link_text: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "br":
            self.parts.append("\n")
        elif tag == "p" and self.parts:
            self.parts.append("\n\n")
        elif tag == "a":
            self._link = values
            self._link_text = []
        elif tag == "span" and "invisible" in values.get("class", "").split():
            self._hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link is not None:
            self.parts.append(self._render_link(self._link, "".join(self._link_text)))
            self._link = None

    def handle_data(self, data: str) -> None:
        if self._link is not None:
            self._link_text.append(data)
        else:
            self.parts.append(data)

    @staticmethod
    def _render_link(attributes: dict[str, str], text: str) -> str:
        classes = attributes.get("class", "").split()
        href = attributes.get("href", "")
        if "hashtag" in classes:
            return text
        if "mention" in classes and text.startswith("@"):
            host = re.sub(r"^https?://([^/]+)/.*$", r"\1", href)
            return f"{text}@{host}" if "@" not in text[1:] else text
        return href or text


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    return "".join(extractor.parts).strip()


def mentions(text: str) -> list[str]:
    return [f"@{user}@{host}" for user, host in MENTION_RE.findall(text)]


def rewrite_mentions(text: str, network: str) -> str:
    if network in FEDIVERSE:
        return text
    if network == "x":
        return MENTION_RE.sub(r"\1", text)
    return MENTION_RE.sub(r"\1 (https://\2/@\1)", text)


def compose(template: str, text: str, source_url: str, network: str) -> str:
    frame = template.replace("{source_url}", source_url)
    overhead = count(frame.replace("{text}", ""), network)
    body = shorten(rewrite_mentions(text, network), network, reserve=overhead)
    return frame.replace("{text}", body)


@dataclass(frozen=True)
class Attachment:
    media: Media
    alt_text: str
    jpeg: bool


@dataclass(frozen=True)
class Plan:
    title: str
    text: str
    profile: str
    media: tuple[Attachment, ...]
    draft_only: bool
    skip: str


MASTODON_VIDEO_BYTES = 99 * 1024 * 1024
JPEG_ONLY = frozenset({"instagram"})
NEEDS_MEDIA = frozenset({"pixelfed"})


def _transferable(media: Media, network: str) -> bool:
    return not (
        network == "mastodon"
        and media.mime.startswith("video/")
        and media.size > MASTODON_VIDEO_BYTES
    )


def prepare(item: SourceItem, network: str, template: str, mode: str) -> Plan:
    body = f"{item.title}\n\n{item.text}".strip() if item.title else item.text
    attachments = tuple(
        Attachment(
            media,
            media.description,
            network in JPEG_ONLY and media.mime.startswith("image/"),
        )
        for media in item.media
        if _transferable(media, network)
    )
    if len(attachments) < len(item.media) and "{source_url}" not in template:
        template = template + "\n\n{source_url}"
    skip = (
        f"{network} accepts only posts with media"
        if network in NEEDS_MEDIA and not attachments
        else ""
    )
    kinds = {attachment.media.mime.split("/", 1)[0] for attachment in attachments}
    profile = "video" if "video" in kinds else "image_post" if kinds else "short_text"
    unmappable = bool(mentions(item.text)) and network not in FEDIVERSE
    return Plan(
        title=item.title or body.split("\n", 1)[0][:100],
        text=compose(template, body, item.url, network),
        profile=profile,
        media=attachments,
        draft_only=mode == "review" or bool(item.spoiler) or unmappable,
        skip=skip,
    )
