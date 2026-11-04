#!/usr/bin/env python3
"""Import every mailbox of a Mailu maildir volume into Stalwart.

Args:
    --maildir-root: Mailu ``dovecot_mail`` volume root, one ``<address>/`` tree per mailbox.
    --imap-host: Stalwart IMAPS host.
    --imap-port: Stalwart IMAPS port.
    --imap-insecure: skip TLS verification of the IMAPS hop.
    --jmap-url: Stalwart JMAP API endpoint, e.g. ``http://127.0.0.1:8095/jmap/``.
    --admin-file: JSON ``{"user": ..., "password": ...}`` of Stalwart's recovery administrator.
    --mailbox-map: JSON list ``[{"source": ..., "target": ...}]`` merging a mailbox into another account.
    --workers: IMAP sessions appending in parallel per mailbox.
    --done-file: marker written once an import ends without a failure.
"""

from __future__ import annotations

import argparse
import base64
import imaplib
import json
import ssl
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from imap_layout import (
    MigrationError,
    destination_mailbox,
    existing_keys,
    imap_quote,
    server_layout,
)
from mailu_maildir import (
    Mailbox,
    SieveScript,
    dedup_key,
    discover_mailboxes,
    domain_of,
    iter_maildir_folders,
    iter_messages,
    maildir_flags_to_imap,
    parse_mailbox_map,
    plan_imports,
    read_active_sieve,
    read_keywords,
    sieve_script_name,
)

_ADMIN_USING = ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]
_SIEVE_CAPABILITY = "urn:ietf:params:jmap:sieve"
_SIEVE_USING = ["urn:ietf:params:jmap:core", _SIEVE_CAPABILITY]
_BLOB_USING = ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:blob"]
_HTTP_TIMEOUT = 60
_IMAP_TIMEOUT = 60
_PROGRESS_EVERY = 1000
_LOOPBACK_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass
class FolderStats:
    found: int = 0
    appended: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass
class AccountStats:
    folders: dict[str, FolderStats] = field(default_factory=dict)

    def folder(self, name: str) -> FolderStats:
        return self.folders.setdefault(name, FolderStats())

    def total(self, attribute: str) -> int:
        return sum(getattr(f, attribute) for f in self.folders.values())


def append_messages(
    imaps: list[imaplib.IMAP4],
    mailbox: str,
    messages: list[Path],
    keywords: dict[str, str],
    present: set[str],
    fstats: FolderStats,
) -> None:
    lock = threading.Lock()
    pending = iter(messages)

    def worker(imap: imaplib.IMAP4) -> None:
        while True:
            with lock:
                msg_path = next(pending, None)
            if msg_path is None:
                return
            raw = msg_path.read_bytes()
            key = dedup_key(raw)
            with lock:
                if key and key in present:
                    fstats.skipped += 1
                    continue
                present.add(key)
            flags = maildir_flags_to_imap(msg_path.name, keywords)
            internal_date = imaplib.Time2Internaldate(msg_path.stat().st_mtime)
            typ, data = imap.append(
                imap_quote(mailbox), flags or None, internal_date, raw
            )
            with lock:
                if typ == "OK":
                    fstats.appended += 1
                else:
                    print(f"  [FAIL] APPEND {msg_path.name}: {data}", file=sys.stderr)
                    fstats.failed += 1
                done = fstats.appended + fstats.skipped + fstats.failed
                if done % _PROGRESS_EVERY == 0:
                    print(f"  [PROGRESS] {mailbox}: {done}/{fstats.found}")

    with ThreadPoolExecutor(max_workers=len(imaps)) as pool:
        list(pool.map(worker, imaps))


def migrate_account(
    imaps: list[imaplib.IMAP4], account_dir: Path, stats: AccountStats
) -> None:
    imap = imaps[0]
    layout = server_layout(imap)
    for maildir_name, folder_dir in iter_maildir_folders(account_dir):
        mailbox = destination_mailbox(maildir_name, layout)
        fstats = stats.folder(mailbox)
        messages = iter_messages(folder_dir)
        fstats.found += len(messages)
        if mailbox.upper() != "INBOX":
            imap.create(imap_quote(mailbox))
        typ, _ = imap.select(imap_quote(mailbox))
        if typ != "OK":
            print(f"  [FAIL] cannot SELECT {mailbox!r}", file=sys.stderr)
            fstats.failed += len(messages)
            continue
        append_messages(
            imaps,
            mailbox,
            messages,
            read_keywords(folder_dir),
            existing_keys(imap),
            fstats,
        )


class Jmap:
    def __init__(self, url: str, user: str, password: str) -> None:
        self.url = url.rstrip("/") + "/"
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }

    def _send(self, url: str, payload: object | None) -> dict:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(  # noqa: S310 fixed internal JMAP origin
            url, data=data, headers=self.headers
        )
        with _LOOPBACK_OPENER.open(request, timeout=_HTTP_TIMEOUT) as response:
            return json.loads(response.read())

    def session(self) -> dict:
        return self._send(self.url + "session", None)

    def call(self, using: list[str], method: str, arguments: dict) -> dict:
        body = self._send(
            self.url, {"using": using, "methodCalls": [[method, arguments, "c0"]]}
        )
        name, result, _ = body["methodResponses"][0]
        if name == "error":
            raise MigrationError(f"{method} refused: {result}")
        rejected = {
            **(result.get("notCreated") or {}),
            **(result.get("notUpdated") or {}),
        }
        if rejected:
            raise MigrationError(f"{method} rejected: {rejected}")
        return result


class Stalwart:
    def __init__(self, url: str, admin_user: str, admin_password: str) -> None:
        self.url = url
        self.admin_user = admin_user
        self.admin_password = admin_password
        self.admin = Jmap(url, admin_user, admin_password)

    def impersonation_login(self, address: str) -> str:
        return f"{address}%{self.admin_user}"

    def domains(self) -> dict[str, str]:
        listed = self.admin.call(_ADMIN_USING, "x:Domain/get", {"ids": None})["list"]
        return {d["name"].lower(): d["id"] for d in listed}

    def addresses(self, method: str, domains: dict[str, str]) -> set[str]:
        names = {domain_id: name for name, domain_id in domains.items()}
        listed = self.admin.call(_ADMIN_USING, method, {"ids": None})["list"]
        return {
            f"{item['name']}@{names[item['domainId']]}".lower()
            for item in listed
            if item.get("domainId") in names
        }

    def create_account(self, address: str, domain_id: str) -> None:
        account = {
            "@type": "User",
            "name": address.partition("@")[0],
            "domainId": domain_id,
            "description": address,
        }
        self.admin.call(_ADMIN_USING, "x:Account/set", {"create": {"a": account}})

    def import_sieve(self, address: str, script: SieveScript) -> str:
        jmap = Jmap(self.url, self.impersonation_login(address), self.admin_password)
        account_id = jmap.session()["primaryAccounts"][_SIEVE_CAPABILITY]
        listed = jmap.call(
            _SIEVE_USING, "SieveScript/get", {"accountId": account_id, "ids": None}
        )["list"]
        current = next((s for s in listed if s["name"] == script.name), None)
        if (
            current
            and _blob_text(jmap, account_id, current["blobId"]) == script.content
        ):
            return f"unchanged:{script.name}"
        blob_id = jmap.call(
            _BLOB_USING,
            "Blob/upload",
            {
                "accountId": account_id,
                "create": {"b": {"data": [{"data:asText": script.content}]}},
            },
        )["created"]["b"]["id"]
        change = (
            {"update": {current["id"]: {"blobId": blob_id}}}
            if current
            else {"create": {"s": {"name": script.name, "blobId": blob_id}}}
        )
        jmap.call(
            _SIEVE_USING,
            "SieveScript/set",
            {
                "accountId": account_id,
                **change,
                "onSuccessActivateScript": current["id"] if current else "#s",
            },
        )
        return f"{'updated' if current else 'imported'}:{script.name} (active)"


def _blob_text(jmap: Jmap, account_id: str, blob_id: str) -> str:
    listed = jmap.call(
        _BLOB_USING,
        "Blob/get",
        {"accountId": account_id, "ids": [blob_id], "properties": ["data:asText"]},
    )["list"]
    return listed[0].get("data:asText", "") if listed else ""


def connect(host: str, port: int, insecure: bool) -> imaplib.IMAP4_SSL:
    context = ssl.create_default_context()
    if insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    imap = imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=_IMAP_TIMEOUT)
    imap._encoding = "utf-8"
    return imap


def open_session(
    args: argparse.Namespace, stalwart: Stalwart, target: str
) -> imaplib.IMAP4_SSL:
    imap = connect(args.imap_host, args.imap_port, args.imap_insecure)
    imap.login(
        imap_quote(stalwart.impersonation_login(target)), stalwart.admin_password
    )
    return imap


def open_sessions(
    args: argparse.Namespace, stalwart: Stalwart, target: str
) -> list[imaplib.IMAP4_SSL]:
    imaps = [open_session(args, stalwart, target)]
    for _ in range(args.workers - 1):
        try:
            imaps.append(open_session(args, stalwart, target))
        except (imaplib.IMAP4.error, OSError) as error:
            print(f"[WARN] {target}: continuing with {len(imaps)} sessions: {error}")
            break
    return imaps


def import_mailbox(
    args: argparse.Namespace, stalwart: Stalwart, source: Mailbox, target: str
) -> AccountStats:
    stats = AccountStats()
    imaps = open_sessions(args, stalwart, target)
    try:
        migrate_account(imaps, source.path, stats)
    finally:
        for imap in imaps:
            with suppress(imaplib.IMAP4.error, OSError):
                imap.logout()
    return stats


def import_sieve_of(stalwart: Stalwart, source: Mailbox, target: str) -> str:
    script = read_active_sieve(source.path)
    if script is None:
        return "none"
    name = sieve_script_name(source.address, target, script.name)
    return stalwart.import_sieve(target, SieveScript(name, script.content))


def import_target(
    args: argparse.Namespace, stalwart: Stalwart, target: str, sources: list[Mailbox]
) -> int:
    failures = 0
    activated: list[str] = []
    for source in sources:
        try:
            stats = import_mailbox(args, stalwart, source, target)
            sieve = import_sieve_of(stalwart, source, target)
        except (MigrationError, imaplib.IMAP4.error, OSError) as error:
            print(f"[FAIL] {source.address} -> {target}: {error}", file=sys.stderr)
            failures += 1
            continue
        if sieve.endswith("(active)"):
            activated.append(sieve)
        print(
            f"[MAILBOX] {source.address} -> {target}: found={stats.total('found')} "
            f"imported={stats.total('appended')} skipped={stats.total('skipped')} "
            f"failed={stats.total('failed')} sieve={sieve}"
        )
        for mailbox, f in sorted(stats.folders.items()):
            print(
                f"  {mailbox}: found={f.found} imported={f.appended} "
                f"skipped={f.skipped} failed={f.failed}"
            )
        failures += stats.total("failed")
    if len(activated) > 1:
        print(f"[WARN] {target}: several Sieve scripts imported, {activated[-1]} wins")
    return failures


def ensure_account(
    stalwart: Stalwart,
    target: str,
    domains: dict[str, str],
    accounts: set[str],
    lists: set[str],
) -> None:
    if target in accounts:
        return
    if target in lists:
        raise MigrationError(
            f"{target} is a mail alias; map its mailbox onto an account in mailbox_map"
        )
    stalwart.create_account(target, domains[domain_of(target)])
    print(f"[ACCOUNT] created {target}")


def run(args: argparse.Namespace) -> int:
    admin = json.loads(Path(args.admin_file).read_text(encoding="utf-8"))
    stalwart = Stalwart(args.jmap_url, admin["user"], admin["password"])
    domains = stalwart.domains()
    plan = plan_imports(
        discover_mailboxes(Path(args.maildir_root)),
        parse_mailbox_map(args.mailbox_map),
        set(domains),
    )
    for address, reason in plan.skipped:
        print(f"[SKIP] {address}: {reason}")
    for source in plan.missing_sources:
        print(f"[WARN] mailbox_map source {source} has no maildir")
    accounts = stalwart.addresses("x:Account/get", domains)
    lists = stalwart.addresses("x:MailingList/get", domains)
    failures = 0
    for target, sources in sorted(plan.targets.items()):
        try:
            ensure_account(stalwart, target, domains, accounts, lists)
        except (MigrationError, OSError) as error:
            print(f"[FAIL] {target}: {error}", file=sys.stderr)
            failures += 1
            continue
        failures += import_target(args, stalwart, target, sources)
    mailboxes = sum(len(sources) for sources in plan.targets.values())
    print(
        f"[SUMMARY] mailboxes={mailboxes} accounts={len(plan.targets)} "
        f"skipped={len(plan.skipped)} failed={failures}"
    )
    return 1 if failures else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maildir-root", required=True)
    parser.add_argument("--imap-host", required=True)
    parser.add_argument("--imap-port", type=int, required=True)
    parser.add_argument("--imap-insecure", action="store_true")
    parser.add_argument("--jmap-url", required=True)
    parser.add_argument("--admin-file", required=True)
    parser.add_argument("--mailbox-map", required=True)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--done-file", required=True)
    return parser.parse_args(argv)


def mark_done(done_file: Path, started: float) -> None:
    done_file.write_text(f"{started:.0f}\n", encoding="utf-8")


if __name__ == "__main__":
    start = time.time()
    arguments = parse_args()
    rc = run(arguments)
    if rc == 0:
        mark_done(Path(arguments.done_file), start)
    print(f"[DONE] rc={rc} in {time.time() - start:.1f}s")
    raise SystemExit(rc)
