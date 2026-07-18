#!/usr/bin/env python3
"""Seed a Mailu-layout Dovecot maildir fixture for the migration test.

Creates ``<root>/<email>/`` with:
  - INBOX: one SEEN message (``cur/…:2,S``) and one unseen (``new/``),
  - ``.Archive``: one message,
each with a deterministic Message-ID/Subject the verifier asserts on.
"""

from __future__ import annotations

import sys
from pathlib import Path

FIXTURES = (
    # (maildir folder, subdir, filename, message-id, subject, seen)
    (
        "",
        "cur",
        "1700000001.M1.mailu:2,S",
        "<mig-1@mailu.fixture>",
        "Migrated one",
        True,
    ),
    ("", "new", "1700000002.M2.mailu", "<mig-2@mailu.fixture>", "Migrated two", False),
    (
        ".Archive",
        "cur",
        "1700000003.M3.mailu:2,",
        "<mig-3@mailu.fixture>",
        "Archived three",
        False,
    ),
)


def seed(root: Path, address: str) -> None:
    account = root / address
    for folder, sub, filename, message_id, subject, _seen in FIXTURES:
        base = account / folder if folder else account
        for required in ("cur", "new", "tmp"):
            (base / required).mkdir(parents=True, exist_ok=True)
        body = (
            f"Message-ID: {message_id}\r\n"
            f"From: sender@mailu.fixture\r\n"
            f"To: {address}\r\n"
            f"Subject: {subject}\r\n"
            f"Date: Wed, 15 Nov 2023 10:00:00 +0000\r\n"
            f"\r\n"
            f"Body of {subject}.\r\n"
        )
        (base / sub / filename).write_text(body, encoding="utf-8")
    print(f"Seeded {len(FIXTURES)} messages under {account}")


if __name__ == "__main__":
    seed(Path(sys.argv[1]), sys.argv[2])
