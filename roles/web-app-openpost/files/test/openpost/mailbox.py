"""Env (rendered into test.env from templates/test.env.j2):
OPENPOST_MAIL_HOST          IMAPS host of the platform mail server
OPENPOST_MAIL_PASSWORD_B64  base64 password of the administrator mailbox
"""

from __future__ import annotations

import base64
import email
import email.policy
import imaplib
import os
import ssl

from openpost.api import MAIL_RECIPIENT, PROXY_ADDRESS

MAIL_HOST = os.environ["OPENPOST_MAIL_HOST"]
MAIL_PASSWORD = base64.b64decode(os.environ["OPENPOST_MAIL_PASSWORD_B64"]).decode()
IMAPS_PORT = 993
REPORT_SUBJECT = "OpenPost crossposter"
MAILBOXES = ("INBOX", "Junk Mail")


def _reports(imap: imaplib.IMAP4_SSL, mailbox: str) -> list[str]:
    typ, _ = imap.select(f'"{mailbox}"', readonly=True)
    if typ != "OK":
        return []
    typ, data = imap.search(None, "SUBJECT", f'"{REPORT_SUBJECT}"')
    texts = []
    for number in data[0].split() if typ == "OK" and data else []:
        typ, parts = imap.fetch(number, "(BODY.PEEK[])")
        for part in parts if typ == "OK" else []:
            if isinstance(part, tuple):
                message = email.message_from_bytes(part[1], policy=email.policy.default)
                body = message.get_body(("plain",))
                texts.append(body.get_content() if body else "")
    return texts


def reports_naming(urls: list[str]) -> tuple[list[str], str]:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with imaplib.IMAP4_SSL(
            PROXY_ADDRESS or MAIL_HOST, IMAPS_PORT, ssl_context=context, timeout=60
        ) as imap:
            imap._encoding = "utf-8"
            imap.login(MAIL_RECIPIENT, MAIL_PASSWORD)
            texts = [text for mailbox in MAILBOXES for text in _reports(imap, mailbox)]
    except (imaplib.IMAP4.error, OSError) as error:
        return [], f"IMAP {type(error).__name__}: {error}"
    found = [url for url in urls if any(url in text for text in texts)]
    return found, f"{len(texts)} crossposter report(s) in {', '.join(MAILBOXES)}"
