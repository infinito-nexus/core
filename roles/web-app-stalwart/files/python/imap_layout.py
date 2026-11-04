"""Map Mailu maildir folders onto Stalwart's IMAP folders and read what is there."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mailu_maildir import dedup_key, maildir_folder_to_imap

if TYPE_CHECKING:
    import imaplib

_SPECIAL_USE = {
    "sent": "\\Sent",
    "trash": "\\Trash",
    "junk": "\\Junk",
    "spam": "\\Junk",
    "drafts": "\\Drafts",
}
_LIST_LINE = re.compile(
    r'^\((?P<attributes>[^)]*)\) (?:"(?P<separator>[^"]*)"|NIL) (?P<name>.+)$'
)
_KEY_FETCH = "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID DATE FROM TO SUBJECT)])"
_FETCH_CHUNK = 500


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServerLayout:
    separator: str
    special_use: dict[str, str]


def imap_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _imap_unquote(name: str) -> str:
    if len(name) >= 2 and name[0] == name[-1] == '"':
        return name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return name


def server_layout(imap: imaplib.IMAP4) -> ServerLayout:
    typ, lines = imap.list()
    if typ != "OK":
        raise MigrationError(f"LIST failed: {lines}")
    separators: set[str] = set()
    special_use: dict[str, str] = {}
    for line in lines or []:
        if not isinstance(line, bytes):
            continue
        match = _LIST_LINE.match(line.decode("utf-8", "replace"))
        if not match:
            continue
        if match.group("separator"):
            separators.add(match.group("separator"))
        for attribute in match.group("attributes").split():
            if attribute in _SPECIAL_USE.values():
                special_use.setdefault(attribute, _imap_unquote(match.group("name")))
    if len(separators) != 1:
        raise MigrationError(f"cannot tell the hierarchy separator from LIST: {lines}")
    return ServerLayout(separators.pop(), special_use)


def destination_mailbox(maildir_name: str, layout: ServerLayout) -> str:
    mailbox = maildir_folder_to_imap(maildir_name, layout.separator)
    attribute = _SPECIAL_USE.get(mailbox.lower())
    return layout.special_use.get(attribute, mailbox) if attribute else mailbox


def existing_keys(imap: imaplib.IMAP4) -> set[str]:
    """Dedup keys of the SELECTed folder, fetched client-side.

    ``SEARCH HEADER`` is not used: Stalwart indexes headers asynchronously, so a
    search right after APPEND misses fresh messages.
    """
    typ, nums = imap.search(None, "ALL")
    if typ != "OK":
        raise MigrationError(f"SEARCH failed: {nums}")
    sequence = [n.decode() for n in (nums[0] or b"").split()] if nums else []
    keys: set[str] = set()
    for start in range(0, len(sequence), _FETCH_CHUNK):
        chunk = ",".join(sequence[start : start + _FETCH_CHUNK])
        typ, data = imap.fetch(chunk, _KEY_FETCH)
        if typ != "OK":
            raise MigrationError(f"FETCH of the dedup headers failed: {data}")
        keys.update(
            key
            for part in data or []
            if isinstance(part, tuple) and (key := dedup_key(part[1]))
        )
    return keys
