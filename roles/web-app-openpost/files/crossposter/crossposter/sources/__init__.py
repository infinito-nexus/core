from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Media:
    url: str
    mime: str
    description: str
    size: int


@dataclass(frozen=True)
class SourceItem:
    uri: str
    url: str
    platform: str
    text: str
    visibility: str
    tags: tuple[str, ...]
    media: tuple[Media, ...]
    in_reply_to: str
    reblog: bool
    spoiler: str
    application: str
    title: str = ""
    cursor: str = ""
