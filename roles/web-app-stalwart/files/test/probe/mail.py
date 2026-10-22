#!/usr/bin/env python3
"""Send one message, or probe relaying, without depending on curl's optional protocols.

`curl` is built per distro and its SMTP protocol handler is optional: on CentOS
the system curl reports `Protocol "smtp" not supported`, so a harness that
shells out to it passes on Debian and fails on CentOS for reasons that have
nothing to do with the mail server. Python's stdlib carries the protocol on
every distro the matrix runs.

    mail.py send <host> <from> <rcpt> <eml-file>
    mail.py relay <host> <sender> <password>

`relay` exits 0 when an unauthenticated session is refused an external recipient
and the same recipient is accepted once `<sender>` has authenticated, 1 otherwise.
Certificate verification is off: the loopback hop reaches Stalwart's bootstrap
certificate, which matches no hostname.
"""

from __future__ import annotations

import smtplib
import ssl
import sys
from pathlib import Path

SMTP_PORT = 25
SMTPS_PORT = 465
TIMEOUT = 60

EXTERNAL_RECIPIENT = "relay-probe@example.org"
RELAY_DENIED = 550


def unverified_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def send(host: str, sender: str, recipient: str, eml_path: str) -> int:
    message = Path(eml_path).read_bytes()
    with smtplib.SMTP(host, SMTP_PORT, timeout=TIMEOUT) as smtp:
        smtp.sendmail(sender, [recipient], message)
    return 0


def relay(host: str, sender: str, password: str) -> int:
    with smtplib.SMTP(host, SMTP_PORT, timeout=TIMEOUT) as smtp:
        smtp.ehlo()
        smtp.mail(sender)
        anonymous, _ = smtp.rcpt(EXTERNAL_RECIPIENT)
    if anonymous != RELAY_DENIED:
        print(
            f"relay not denied: an unauthenticated session got {anonymous} "
            f"for {EXTERNAL_RECIPIENT}, expected {RELAY_DENIED}",
            file=sys.stderr,
        )
        return 1

    with smtplib.SMTP_SSL(
        host, SMTPS_PORT, timeout=TIMEOUT, context=unverified_context()
    ) as smtp:
        try:
            smtp.login(sender, password)
        except smtplib.SMTPAuthenticationError as error:
            print(
                f"submission refused: {sender} cannot authenticate ({error.smtp_code})",
                file=sys.stderr,
            )
            return 1
        smtp.mail(sender)
        authenticated, _ = smtp.rcpt(EXTERNAL_RECIPIENT)
    if authenticated != 250:
        print(
            f"submission refused: {sender} authenticated but got {authenticated} "
            f"for {EXTERNAL_RECIPIENT}",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    action, args = argv[1], argv[2:]
    if action == "send" and len(args) == 4:
        return send(*args)
    if action == "relay" and len(args) == 3:
        return relay(*args)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
