#!/usr/bin/env python3
"""Inspect a deployed Stalwart as its recovery administrator.

    stalwart.py message <address> <mailbox> <subject> <flags> <epoch>
    stalwart.py absent account|domain <name>
    stalwart.py routing

Args:
    message: exit 0 when <address> holds exactly one <subject> in <mailbox>, carrying
        every flag of the comma list <flags> ('-' for none) and, unless <epoch> is '-',
        that internal date.
    absent: exit 0 when Stalwart knows no such account address or domain.
    routing: send through every alias and forward of STALWART_ALIASES_JSON and
        STALWART_FORWARDS_JSON and wait until each destination got its copy. An
        alias destination outside MAIL_DOMAIN counts once Stalwart queued this
        run's copy for it or the bounce naming it and the subject reaches the
        sender. A forward destination outside MAIL_DOMAIN counts once the
        account's active Sieve script redirects a copy to it: Stalwart sends no
        bounce for a message a Sieve script generated.

Environment: STALWART_ADMIN_USER, STALWART_ADMIN_PASSWORD, STALWART_JMAP_URL,
MAIL_DOMAIN and, for routing, ADMIN_EMAIL, STALWART_ALIASES_JSON, STALWART_FORWARDS_JSON.
"""

from __future__ import annotations

import base64
import contextlib
import email.utils
import imaplib
import json
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.request
from datetime import datetime
from email.message import EmailMessage

HOST = "127.0.0.1"
IMAPS_PORT = 993
SMTP_PORT = 25
TIMEOUT = 60
MAILBOXES = ("INBOX", "Junk Mail")
POLL_ATTEMPTS = 36
POLL_DELAY = 5
ADMIN_USING = ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]
SIEVE_USING = ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:sieve"]
BLOB_USING = ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:blob"]
MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_FLAGS = re.compile(rb"FLAGS \(([^)]*)\)")
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"missing {name}")
    return value


def domain_of(address: str) -> str:
    return address.rpartition("@")[2]


def login(address: str) -> imaplib.IMAP4_SSL:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    imap = imaplib.IMAP4_SSL(HOST, IMAPS_PORT, ssl_context=context, timeout=TIMEOUT)
    imap._encoding = "utf-8"
    imap.login(
        f'"{address}%{env("STALWART_ADMIN_USER")}"', env("STALWART_ADMIN_PASSWORD")
    )
    return imap


def matching(imap: imaplib.IMAP4, mailbox: str, subject: str) -> list[bytes]:
    typ, _ = imap.select(f'"{mailbox}"', readonly=True)
    if typ != "OK":
        return []
    typ, data = imap.search(None, "ALL")
    numbers = (data[0] or b"").split() if typ == "OK" and data else []
    found: list[bytes] = []
    for number in numbers:
        typ, parts = imap.fetch(
            number, "(FLAGS INTERNALDATE BODY.PEEK[HEADER.FIELDS (SUBJECT)])"
        )
        found.extend(
            part[0]
            for part in parts or []
            if isinstance(part, tuple) and subject.encode() in part[1]
        )
    return found


def message(address: str, mailbox: str, subject: str, flags: str, epoch: str) -> int:
    imap = login(address)
    try:
        hits = matching(imap, mailbox, subject)
    finally:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            imap.logout()
    if len(hits) != 1:
        print(
            f"{address}/{mailbox}: {len(hits)} messages titled {subject}",
            file=sys.stderr,
        )
        return 1
    flag_match = _FLAGS.search(hits[0])
    seen = set(flag_match.group(1).decode().split()) if flag_match else set()
    wanted = set() if flags == "-" else set(flags.split(","))
    if not wanted <= seen:
        print(
            f"{subject}: flags {sorted(seen)} lack {sorted(wanted - seen)}",
            file=sys.stderr,
        )
        return 1
    if epoch == "-":
        return 0
    stamp = imaplib.Internaldate2tuple(hits[0])
    if stamp is None or int(time.mktime(stamp)) != int(epoch):
        print(f"{subject}: internal date {stamp} is not {epoch}", file=sys.stderr)
        return 1
    return 0


def http(path: str, payload: dict | None, act_as: str) -> dict:
    login = (
        f"{act_as}%{env('STALWART_ADMIN_USER')}"
        if act_as
        else env("STALWART_ADMIN_USER")
    )
    token = base64.b64encode(
        f"{login}:{env('STALWART_ADMIN_PASSWORD')}".encode()
    ).decode()
    request = urllib.request.Request(  # noqa: S310 fixed internal JMAP origin
        env("STALWART_JMAP_URL") + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
    )
    with _OPENER.open(request, timeout=TIMEOUT) as response:
        return json.loads(response.read())


def call(using: list[str], method: str, arguments: dict, act_as: str) -> dict:
    body = http(
        "", {"using": using, "methodCalls": [[method, arguments, "c0"]]}, act_as
    )
    return body["methodResponses"][0][1]


def jmap(method: str) -> list[dict]:
    return call(ADMIN_USING, method, {"ids": None}, "")["list"]


def active_sieve(address: str) -> str:
    account = http("session", None, address)["primaryAccounts"][SIEVE_USING[1]]
    scripts = call(
        SIEVE_USING, "SieveScript/get", {"accountId": account, "ids": None}, address
    )["list"]
    active = [s["blobId"] for s in scripts if s.get("isActive")]
    if not active:
        return ""
    blobs = call(
        BLOB_USING,
        "Blob/get",
        {"accountId": account, "ids": active, "properties": ["data:asText"]},
        address,
    )
    return blobs["list"][0].get("data:asText", "")


def absent(kind: str, name: str) -> int:
    domains = {d["id"]: d["name"].lower() for d in jmap("x:Domain/get")}
    if kind == "domain":
        known = set(domains.values())
    else:
        known = {
            f"{a['name']}@{domains.get(a.get('domainId'), '')}".lower()
            for a in jmap("x:Account/get")
        }
    if name.lower() in known:
        print(f"{kind} {name} exists in Stalwart", file=sys.stderr)
        return 1
    return 0


def send(sender: str, recipient: str, subject: str) -> None:
    mail = EmailMessage()
    mail["From"], mail["To"], mail["Subject"] = sender, recipient, subject
    mail["Date"] = email.utils.formatdate()
    mail["Message-ID"] = email.utils.make_msgid(domain=domain_of(sender))
    mail.set_content(f"routing probe {subject}")
    with smtplib.SMTP(HOST, SMTP_PORT, timeout=TIMEOUT) as smtp:
        smtp.send_message(mail, from_addr=sender, to_addrs=[recipient])
    print(f"sent: {subject} -> {recipient}")


def since_yesterday() -> str:
    day = time.gmtime(time.time() - 86400)
    return f"{day.tm_mday}-{MONTHS[day.tm_mon - 1]}-{day.tm_year}"


def received(address: str, subject: str) -> bool:
    imap = login(address)
    try:
        return any(matching(imap, mailbox, subject) for mailbox in MAILBOXES)
    finally:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            imap.logout()


def bounced(address: str, destination: str, subject: str) -> bool:
    imap = login(address)
    try:
        for mailbox in MAILBOXES:
            typ, _ = imap.select(f'"{mailbox}"', readonly=True)
            if typ != "OK":
                continue
            typ, data = imap.search(None, "SINCE", since_yesterday())
            for number in (data[0] or b"").split() if typ == "OK" and data else []:
                typ, parts = imap.fetch(number, "(BODY.PEEK[])")
                for part in parts or []:
                    if (
                        isinstance(part, tuple)
                        and destination.encode() in part[1]
                        and subject.encode() in part[1]
                    ):
                        return True
    finally:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            imap.logout()
    return False


def queued(destination: str, since: float) -> bool:
    return any(
        destination in json.dumps(item.get("recipients"))
        and datetime.fromisoformat(item["createdAt"]).timestamp() >= since
        for item in jmap("x:QueuedMessage/get")
    )


def wait_for(description: str, probe) -> bool:
    for _ in range(POLL_ATTEMPTS):
        if probe():
            print(f"ok: {description}")
            return True
        time.sleep(POLL_DELAY)
    print(f"FAIL: {description}", file=sys.stderr)
    return False


def routing() -> int:
    aliases = json.loads(env("STALWART_ALIASES_JSON"))
    forwards = json.loads(env("STALWART_FORWARDS_JSON"))
    if not aliases and not forwards:
        print("SKIP: no aliases or forwards declared")
        return 0
    domain, sender, run_id = env("MAIL_DOMAIN"), env("ADMIN_EMAIL"), int(time.time())
    cases: list[tuple[str, str, list[str], bool]] = []
    for index, alias in enumerate(aliases):
        recipient = (
            alias["address"] if alias["local"] else f"nobody-{run_id}{alias['address']}"
        )
        cases.append(
            (
                f"infinito-alias-{run_id}-{index}",
                recipient,
                alias["destinations"],
                False,
            )
        )
    for index, forward in enumerate(forwards):
        destinations = [forward["address"], *forward["destinations"]]
        cases.append(
            (
                f"infinito-forward-{run_id}-{index}",
                forward["address"],
                destinations,
                True,
            )
        )
    started = time.time() - POLL_DELAY
    for subject, recipient, _, _ in cases:
        send(sender, recipient, subject)
    results = []
    for subject, recipient, destinations, forwarded in cases:
        for destination in destinations:
            if domain_of(destination) == domain:
                results.append(
                    wait_for(
                        f"{subject} ({recipient}) reached {destination}",
                        lambda d=destination, s=subject: received(d, s),
                    )
                )
            elif forwarded:
                results.append(
                    wait_for(
                        f"{recipient}'s active Sieve script redirects a copy to {destination}",
                        lambda d=destination, r=recipient: (
                            f'redirect :copy "{d}";' in active_sieve(r)
                        ),
                    )
                )
            else:
                results.append(
                    wait_for(
                        f"{subject} ({recipient}) left for {destination}",
                        lambda d=destination, s=subject: (
                            queued(d, started) or bounced(sender, d, s)
                        ),
                    )
                )
    return 0 if all(results) else 1


def main(argv: list[str]) -> int:
    action, args = (argv[1], argv[2:]) if len(argv) > 1 else ("", [])
    if action == "message" and len(args) == 5:
        return message(*args)
    if action == "absent" and len(args) == 2 and args[0] in ("account", "domain"):
        return absent(*args)
    if action == "routing" and not args:
        return routing()
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
