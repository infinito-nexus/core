#!/usr/bin/env python3
"""Verify the Mailu->Stalwart migration fixture over IMAP.

Asserts exactly what seed_mailu_maildir.py planted (also serving as the
idempotency check: counts MUST stay exact after a second migration run):
  - INBOX: exactly 2 messages, subjects "Migrated one" + "Migrated two",
    and "Migrated one" kept its \\Seen flag,
  - Archive: exactly 1 message, subject "Archived three".
"""

from __future__ import annotations

import imaplib
import ssl
import sys


def fetch_subject_and_flags(imap: imaplib.IMAP4, num: bytes) -> tuple[str, str]:
    typ, data = imap.fetch(num, "(FLAGS BODY.PEEK[HEADER.FIELDS (SUBJECT)])")
    assert typ == "OK", f"FETCH failed: {data}"
    flags = ""
    subject = ""
    for part in data:
        if isinstance(part, tuple):
            subject = part[1].decode().replace("Subject:", "").strip()
            flags = part[0].decode()
        elif isinstance(part, bytes) and b"FLAGS" in part:
            flags += part.decode()
    return subject, flags


def check_folder(imap: imaplib.IMAP4, mailbox: str, expected: dict[str, bool]) -> None:
    typ, data = imap.select(mailbox, readonly=True)
    assert typ == "OK", f"cannot SELECT {mailbox}"
    count = int(data[0])
    assert count == len(expected), (
        f"{mailbox}: expected {len(expected)} messages, found {count}"
    )
    typ, nums = imap.search(None, "ALL")
    assert typ == "OK"
    seen_subjects: dict[str, bool] = {}
    for num in nums[0].split():
        subject, flags = fetch_subject_and_flags(imap, num)
        seen_subjects[subject] = "\\Seen" in flags
    for subject, want_seen in expected.items():
        assert subject in seen_subjects, f"{mailbox}: missing subject {subject!r}"
        assert seen_subjects[subject] == want_seen, (
            f"{mailbox}: {subject!r} Seen-flag expected={want_seen} "
            f"got={seen_subjects[subject]}"
        )
    print(f"OK {mailbox}: {count} messages, subjects + flags match")


def main(host: str, port: int, user: str, password: str) -> None:
    context = ssl.create_default_context()
    # Fixture container serves Stalwart's built-in bootstrap certificate.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    imap = imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=30)
    try:
        imap.login(user, password)
        check_folder(imap, "INBOX", {"Migrated one": True, "Migrated two": False})
        check_folder(imap, "Archive", {"Archived three": False})
    finally:
        imap.logout()


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4])
