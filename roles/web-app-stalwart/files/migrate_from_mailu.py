#!/usr/bin/env python3
"""Migrate mailbox data from a Mailu installation into Stalwart.

Mailu stores mail as standard Dovecot Maildir under its ``dovecot_mail``
volume (one ``<email>/`` tree per account, subfolders as ``.Name`` maildir
folders). Reading that volume directly means NO live Mailu is required —
the migration works against a stopped or legacy-parked instance and the
test harness needs no full platform deploy.

Scope (v1, deliberate):
  - Migrates MESSAGES (folder structure, flags, internal dates) per account
    via IMAP APPEND into Stalwart.
  - Idempotent: a message whose Message-ID already exists in the target
    folder is skipped, so re-runs converge instead of duplicating.
  - Accounts/aliases are NOT created here: on the platform they are
    provisioned from the inventory (web-app-stalwart tasks/04_manage_user.yml);
    the test harness creates its fixture account via the same JMAP API.
  - Sieve filters and CalDAV/CardDAV data are out of scope (documented in
    the role README).

Usage:
  migrate_from_mailu.py --maildir-root /mail --imap-host mail.example.org \
      --accounts-file accounts.json [--imap-port 993] [--imap-insecure] \
      [--dest-separator /]

``accounts.json``: {"<email>": "<imap password>", ...} — the credentials of
the already-provisioned Stalwart accounts (inventory passwords on the
platform; fixture passwords in the test).
"""

from __future__ import annotations

import argparse
import contextlib
import email.parser
import imaplib
import json
import ssl
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Maildir info flags -> IMAP system flags (maildir(5) semantics).
_MAILDIR_FLAG_MAP = {
    "S": "\\Seen",
    "R": "\\Answered",
    "F": "\\Flagged",
    "T": "\\Deleted",
    "D": "\\Draft",
}


@dataclass
class FolderStats:
    appended: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass
class AccountStats:
    folders: dict[str, FolderStats] = field(default_factory=dict)

    def folder(self, name: str) -> FolderStats:
        return self.folders.setdefault(name, FolderStats())

    @property
    def failed(self) -> int:
        return sum(f.failed for f in self.folders.values())


def maildir_flags_to_imap(filename: str) -> str:
    """Map a maildir file's ``:2,<flags>`` suffix to an IMAP flag list string."""
    if ":2," not in filename:
        return ""
    info = filename.rsplit(":2,", 1)[1]
    flags = [_MAILDIR_FLAG_MAP[c] for c in info if c in _MAILDIR_FLAG_MAP]
    return "(" + " ".join(flags) + ")" if flags else ""


def maildir_folder_to_imap(maildir_name: str, separator: str) -> str:
    """Map a maildir folder dir name to the destination IMAP mailbox name.

    ``""`` (the maildir root) is INBOX; ``.Archive.2024`` becomes
    ``Archive<sep>2024`` (dovecot uses ``.`` as the on-disk separator).
    """
    if not maildir_name:
        return "INBOX"
    return maildir_name.lstrip(".").replace(".", separator)


def iter_maildir_folders(account_dir: Path) -> list[tuple[str, Path]]:
    """Yield (maildir_folder_name, path) for the root and every ``.Sub`` dir."""
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
    """All message files of one maildir folder (cur = seen-ish, new = unseen)."""
    messages: list[Path] = []
    for sub in ("cur", "new"):
        subdir = folder_dir / sub
        if subdir.is_dir():
            messages.extend(p for p in sorted(subdir.iterdir()) if p.is_file())
    return messages


def extract_message_id(raw: bytes) -> str:
    """Message-ID header value from raw RFC-5322 bytes ('' when absent)."""
    parser = email.parser.BytesHeaderParser()
    try:
        return (parser.parsebytes(raw).get("Message-ID") or "").strip()
    except Exception:
        return ""


_FETCH_CHUNK = 500


def existing_message_ids(imap: imaplib.IMAP4) -> set[str]:
    """Message-IDs already present in the SELECTed folder.

    Fetched client-side (one header-fields FETCH per chunk) instead of
    ``SEARCH HEADER``: Stalwart indexes headers asynchronously, so a
    server-side search right after APPEND misses fresh messages — the
    harness's idempotency step caught exactly that as duplicates.
    """
    typ, nums = imap.search(None, "ALL")
    if typ != "OK" or not nums or not nums[0].split():
        return set()
    sequence = [n.decode() for n in nums[0].split()]
    ids: set[str] = set()
    for start in range(0, len(sequence), _FETCH_CHUNK):
        chunk = ",".join(sequence[start : start + _FETCH_CHUNK])
        typ, data = imap.fetch(chunk, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
        if typ != "OK":
            continue
        for part in data or []:
            if isinstance(part, tuple):
                message_id = extract_message_id(part[1])
                if message_id:
                    ids.add(message_id)
    return ids


def ensure_mailbox(imap: imaplib.IMAP4, mailbox: str) -> None:
    """CREATE the mailbox; 'already exists' answers are fine."""
    if mailbox.upper() == "INBOX":
        return
    imap.create(mailbox)


def migrate_account(
    imap: imaplib.IMAP4,
    account_dir: Path,
    separator: str,
    stats: AccountStats,
) -> None:
    for maildir_name, folder_dir in iter_maildir_folders(account_dir):
        mailbox = maildir_folder_to_imap(maildir_name, separator)
        fstats = stats.folder(mailbox)
        ensure_mailbox(imap, mailbox)
        typ, _ = imap.select(mailbox)
        if typ != "OK":
            print(f"  [FAIL] cannot SELECT {mailbox!r}", file=sys.stderr)
            fstats.failed += len(iter_messages(folder_dir))
            continue
        present = existing_message_ids(imap)
        for msg_path in iter_messages(folder_dir):
            raw = msg_path.read_bytes()
            message_id = extract_message_id(raw)
            if message_id and message_id in present:
                fstats.skipped += 1
                continue
            present.add(message_id)
            flags = maildir_flags_to_imap(msg_path.name)
            internal_date = imaplib.Time2Internaldate(msg_path.stat().st_mtime)
            typ, data = imap.append(mailbox, flags or None, internal_date, raw)
            if typ == "OK":
                fstats.appended += 1
            else:
                print(f"  [FAIL] APPEND {msg_path.name}: {data}", file=sys.stderr)
                fstats.failed += 1


def connect(host: str, port: int, insecure: bool) -> imaplib.IMAP4_SSL:
    context = ssl.create_default_context()
    if insecure:
        # Test harness / container-internal hop: the fixture Stalwart serves
        # its built-in bootstrap certificate.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=30)


def run(args: argparse.Namespace) -> int:
    accounts: dict[str, str] = json.loads(
        Path(args.accounts_file).read_text(encoding="utf-8")
    )
    maildir_root = Path(args.maildir_root)
    exit_code = 0

    for address, password in accounts.items():
        account_dir = maildir_root / address
        if not account_dir.is_dir():
            print(f"[SKIP] no maildir for {address} under {maildir_root}")
            continue
        print(f"[ACCOUNT] {address}")
        stats = AccountStats()
        imap = connect(args.imap_host, args.imap_port, args.imap_insecure)
        try:
            imap.login(address, password)
            migrate_account(imap, account_dir, args.dest_separator, stats)
        finally:
            # A failed logout is not a migration failure.
            with contextlib.suppress(Exception):
                imap.logout()
        for mailbox, f in sorted(stats.folders.items()):
            print(
                f"  {mailbox}: appended={f.appended} "
                f"skipped={f.skipped} failed={f.failed}"
            )
        if stats.failed:
            exit_code = 1
    return exit_code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--maildir-root",
        required=True,
        help="Mailu dovecot mail volume root (contains one <email>/ tree per account)",
    )
    parser.add_argument("--imap-host", required=True, help="Stalwart IMAP host")
    parser.add_argument("--imap-port", type=int, default=993)
    parser.add_argument(
        "--imap-insecure",
        action="store_true",
        help="Skip TLS verification (fixture/bootstrap certificates)",
    )
    parser.add_argument(
        "--accounts-file",
        required=True,
        help='JSON file {"<email>": "<password>"} of provisioned Stalwart accounts',
    )
    parser.add_argument(
        "--dest-separator",
        default="/",
        help="IMAP hierarchy separator on the destination (Stalwart: '/')",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    start = time.time()
    rc = run(parse_args())
    print(f"[DONE] rc={rc} in {time.time() - start:.1f}s")
    raise SystemExit(rc)
