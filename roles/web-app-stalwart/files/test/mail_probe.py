#!/usr/bin/env python3
"""Send one message, or look one up, without depending on curl's optional protocols.

`curl` is built per distro and its SMTP and IMAP protocol handlers are optional:
on CentOS the system curl reports `Protocol "smtp" not supported`, so a harness
that shells out to it passes on Debian and fails on CentOS for reasons that have
nothing to do with the mail server. Python's stdlib carries both protocols on
every distro the matrix runs, and the migration script it exercises already
speaks IMAP through imaplib.

    mail_probe.py send <host> <from> <rcpt> <eml-file>
    mail_probe.py find <host> <user> <password> <subject>

`find` exits 0 when the subject is present in INBOX or Junk, 1 when it is not.
Both mailboxes are searched because a test domain publishes no mail-auth DNS, so
a correctly delivered message is legitimately filed under Junk. Certificate
verification is off for the same reason the migration script turns it off: the
loopback hop reaches Stalwart's bootstrap certificate, which matches no hostname.
`imaplib` is forced to UTF-8 for the same reason too — it encodes command
arguments as ASCII, so a password holding any non-ASCII character (the platform
generates passwords containing '€') raises UnicodeEncodeError before LOGIN is
ever sent.
"""

from __future__ import annotations

import contextlib
import imaplib
import smtplib
import ssl
import sys
from pathlib import Path

SMTP_PORT = 25
IMAPS_PORT = 993
TIMEOUT = 60

MAILBOXES = ("INBOX", "Junk Mail")


def send(host: str, sender: str, recipient: str, eml_path: str) -> int:
    message = Path(eml_path).read_bytes()
    with smtplib.SMTP(host, SMTP_PORT, timeout=TIMEOUT) as smtp:
        smtp.sendmail(sender, [recipient], message)
    return 0


def find(host: str, user: str, password: str, subject: str) -> int:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    imap = imaplib.IMAP4_SSL(host, IMAPS_PORT, ssl_context=context, timeout=TIMEOUT)
    imap._encoding = "utf-8"
    try:
        imap.login(user, password)
        for mailbox in MAILBOXES:
            typ, _ = imap.select(f'"{mailbox}"', readonly=True)
            if typ != "OK":
                continue
            typ, data = imap.search(None, "SUBJECT", f'"{subject}"')
            if typ == "OK" and data and data[0].split():
                return 0
    finally:
        with contextlib.suppress(Exception):
            imap.logout()
    return 1


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    action, args = argv[1], argv[2:]
    if action == "send" and len(args) == 4:
        return send(*args)
    if action == "find" and len(args) == 4:
        return find(*args)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
