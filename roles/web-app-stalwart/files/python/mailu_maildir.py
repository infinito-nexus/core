"""Read Mailu's Dovecot maildir volume: mailboxes, folders, flags and Sieve scripts."""

from __future__ import annotations

import email.parser
import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_MAILDIR_FLAG_MAP = {
    "S": "\\Seen",
    "R": "\\Answered",
    "F": "\\Flagged",
    "T": "\\Deleted",
    "D": "\\Draft",
}
_FALLBACK_KEY_HEADERS = ("Date", "From", "To", "Subject")
_SIEVE_ACTIVE_LINK = ".dovecot.sieve"
_SIEVE_RESERVED_NAMES = frozenset({"vacation"})


@dataclass(frozen=True)
class Mailbox:
    address: str
    path: Path


@dataclass(frozen=True)
class SieveScript:
    name: str
    content: str


@dataclass
class ImportPlan:
    targets: dict[str, list[Mailbox]]
    skipped: list[tuple[str, str]]
    missing_sources: list[str]


def domain_of(address: str) -> str:
    return address.rpartition("@")[2]


def is_address(name: str) -> bool:
    local, at, domain = name.rpartition("@")
    return bool(at and local and "@" not in local and "." in domain)


def discover_mailboxes(root: Path) -> list[Mailbox]:
    found = [
        Mailbox(child.name.lower(), child)
        for child in root.iterdir()
        if child.is_dir() and is_address(child.name)
    ]
    return sorted(found, key=lambda mailbox: mailbox.address)


def parse_mailbox_map(raw: str) -> dict[str, str]:
    """Validate the ``[{"source": ..., "target": ...}]`` mapping.

    Raises:
        ValueError: an entry is malformed, a source repeats, or a target is itself mapped.
    """
    mapping: dict[str, str] = {}
    for entry in json.loads(raw):
        source = str(entry["source"]).strip().lower()
        target = str(entry["target"]).strip().lower()
        if not (is_address(source) and is_address(target)) or source == target:
            raise ValueError(f"invalid mailbox_map entry {entry!r}")
        if source in mapping:
            raise ValueError(f"mailbox_map maps {source} twice")
        mapping[source] = target
    chained = sorted(set(mapping.values()) & set(mapping))
    if chained:
        raise ValueError(f"mailbox_map targets are themselves mapped: {chained}")
    return mapping


def plan_imports(
    mailboxes: list[Mailbox], mapping: dict[str, str], served: set[str]
) -> ImportPlan:
    """Group the mailboxes by the Stalwart account they land in.

    Raises:
        ValueError: a mapping target lies in a domain Stalwart does not serve.
    """
    unserved = sorted(t for t in mapping.values() if domain_of(t) not in served)
    if unserved:
        raise ValueError(f"mailbox_map targets outside the served domains: {unserved}")
    targets: dict[str, list[Mailbox]] = {}
    skipped: list[tuple[str, str]] = []
    for mailbox in mailboxes:
        target = mapping.get(mailbox.address, mailbox.address)
        if domain_of(target) not in served:
            reason = f"domain {domain_of(target)} is not served by Stalwart"
            skipped.append((mailbox.address, reason))
            continue
        targets.setdefault(target, []).append(mailbox)
    for target, sources in targets.items():
        sources.sort(key=lambda m: (m.address != target, m.address))
    present = {m.address for m in mailboxes}
    missing = sorted(source for source in mapping if source not in present)
    return ImportPlan(targets, skipped, missing)


def read_keywords(folder_dir: Path) -> dict[str, str]:
    path = folder_dir / "dovecot-keywords"
    if not path.is_file():
        return {}
    letters: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        index, _, name = line.partition(" ")
        if index.isdigit() and int(index) < 26 and name.strip():
            letters[chr(ord("a") + int(index))] = name.strip()
    return letters


def maildir_flags_to_imap(filename: str, keywords: dict[str, str]) -> str:
    if ":2," not in filename:
        return ""
    info = filename.rsplit(":2,", 1)[1]
    flags = [_MAILDIR_FLAG_MAP[c] for c in info if c in _MAILDIR_FLAG_MAP]
    flags += [keywords[c] for c in info if c in keywords]
    return "(" + " ".join(flags) + ")" if flags else ""


def maildir_folder_to_imap(maildir_name: str, separator: str) -> str:
    if not maildir_name:
        return "INBOX"
    return maildir_name.lstrip(".").replace(".", separator)


def iter_maildir_folders(account_dir: Path) -> list[tuple[str, Path]]:
    folders: list[tuple[str, Path]] = []
    if (account_dir / "cur").is_dir() or (account_dir / "new").is_dir():
        folders.append(("", account_dir))
    folders.extend(
        (child.name, child)
        for child in sorted(account_dir.iterdir())
        if child.is_dir()
        and child.name.startswith(".")
        and ((child / "cur").is_dir() or (child / "new").is_dir())
    )
    return folders


def iter_messages(folder_dir: Path) -> list[Path]:
    messages: list[Path] = []
    for sub in ("cur", "new"):
        subdir = folder_dir / sub
        if subdir.is_dir():
            messages.extend(p for p in sorted(subdir.iterdir()) if p.is_file())
    return messages


def _normalize(value: object) -> str:
    return " ".join(str(value or "").split())


def dedup_key(raw: bytes) -> str:
    """Return the Message-ID, else a digest of Date/From/To/Subject, else ''."""
    headers = email.parser.BytesHeaderParser().parsebytes(raw)
    message_id = _normalize(headers.get("Message-ID"))
    if message_id:
        return message_id
    fallback = [_normalize(headers.get(name)) for name in _FALLBACK_KEY_HEADERS]
    if not any(fallback):
        return ""
    return "sha256:" + hashlib.sha256("\0".join(fallback).encode()).hexdigest()


def read_active_sieve(mailbox_dir: Path) -> SieveScript | None:
    link = mailbox_dir / _SIEVE_ACTIVE_LINK
    if link.is_symlink():
        script = mailbox_dir / "sieve" / link.readlink().name
        name = script.stem
    elif link.is_file():
        script, name = link, "dovecot"
    else:
        return None
    if not script.is_file():
        return None
    content = script.read_text(encoding="utf-8")
    return SieveScript(name, content) if content.strip() else None


def sieve_script_name(source: str, target: str, name: str) -> str:
    name = f"mailu-{name}" if name.lower() in _SIEVE_RESERVED_NAMES else name
    return name if source == target else f"{source.partition('@')[0]}-{name}"
