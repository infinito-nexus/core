#!/usr/bin/env python3
"""Stalwart mail-flow end-to-end test.

Provisions a throwaway ``.test`` domain + two accounts in the *running* Stalwart,
sends a message over SMTP submission (465, implicit TLS, authenticated), confirms
receipt via JMAP, then cleans everything up. Exits non-zero on any failure.

Why this works on ANY deploy: Stalwart accepts ``.test`` domains via JMAP even when
the stack's DOMAIN_PRIMARY is a reserved/documentation domain like ``.example`` that
Stalwart otherwise rejects. So this genuinely exercises send -> deliver -> retrieve
without needing the whole stack on a special domain.

Runs inside the infinito dev container and reaches Stalwart through
``compose exec stalwart`` (the same path used during provisioning).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

COMPOSE_DIR = "/opt/compose/stalwart"
BODY_FILE = "/tmp/stalwart_e2e_body.json"
MSG_FILE = "/tmp/stalwart_e2e_msg.txt"
DOMAIN = "e2e-mailflow.test"
ALICE_PW = "alice-Kq9Wm2Zx7Tn4Rp8Vb"
BOB_PW = "bob-Hr5Lc3De6Yq8Wn2Mx4"
USING = ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]


def _sh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=COMPOSE_DIR, capture_output=True, text=True, check=False
    )


def _admin_creds() -> str:
    r = _sh(
        ["compose", "exec", "-T", "stalwart", "printenv", "STALWART_RECOVERY_ADMIN"]
    )
    creds = r.stdout.strip()
    if ":" not in creds:
        sys.exit("FAIL: could not read STALWART_RECOVERY_ADMIN from the container")
    return creds


def _jmap(creds: str, calls: list, using: list[str] | None = None) -> dict:
    body = {"using": using or USING, "methodCalls": calls}
    with open(BODY_FILE, "w") as fh:
        json.dump(body, fh)
    _sh(["compose", "cp", BODY_FILE, "stalwart:/tmp/e2e.json"])
    r = _sh(
        [
            "compose",
            "exec",
            "-T",
            "stalwart",
            "curl",
            "-s",
            "-u",
            creds,
            "-H",
            "Content-Type:application/json",
            "--data-binary",
            "@/tmp/e2e.json",
            "http://localhost:8080/jmap/",
        ]
    )
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        sys.exit(f"FAIL: non-JSON JMAP response: {r.stdout[:300]} {r.stderr[:200]}")


def main() -> int:
    admin = _admin_creds()

    # 1. Provision the throwaway domain.
    resp = _jmap(admin, [["x:Domain/set", {"create": {"d": {"name": DOMAIN}}}, "c0"]])
    created = resp["methodResponses"][0][1].get("created", {})
    if "d" not in created:
        # Domain may already exist from a previous aborted run — resolve its id.
        got = _jmap(admin, [["x:Domain/get", {"ids": None}, "c0"]])
        dom = next(
            (d for d in got["methodResponses"][0][1]["list"] if d["name"] == DOMAIN),
            None,
        )
        if not dom:
            sys.exit(f"FAIL: could not create or find domain {DOMAIN}: {resp}")
        domain_id = dom["id"]
    else:
        domain_id = created["d"]["id"]

    # 2. Provision alice + bob.
    resp = _jmap(
        admin,
        [
            [
                "x:Account/set",
                {
                    "create": {
                        "a": {
                            "@type": "User",
                            "name": "alice",
                            "domainId": domain_id,
                            "credentials": {
                                "0": {"@type": "Password", "secret": ALICE_PW}
                            },
                        },
                        "b": {
                            "@type": "User",
                            "name": "bob",
                            "domainId": domain_id,
                            "credentials": {
                                "0": {"@type": "Password", "secret": BOB_PW}
                            },
                        },
                    }
                },
                "c0",
            ]
        ],
    )
    acct = resp["methodResponses"][0][1]
    created = acct.get("created", {})
    if "a" not in created or "b" not in created:
        _cleanup(admin, domain_id, [])
        sys.exit(f"FAIL: account creation failed: {acct}")
    account_ids = [created["a"]["id"], created["b"]["id"]]

    subject = f"stalwart-e2e {int(time.time())}"
    msg = (
        f"From: alice@{DOMAIN}\r\nTo: bob@{DOMAIN}\r\nSubject: {subject}\r\n\r\n"
        "Automated Stalwart mail-flow e2e: send -> deliver -> retrieve.\r\n"
    )
    with open(MSG_FILE, "w") as fh:
        fh.write(msg)
    _sh(["compose", "cp", MSG_FILE, "stalwart:/tmp/e2e_msg.txt"])

    # 3. Send alice -> bob over SMTP submission (465). Retry on transient defers
    # (the ClamAV milter is fail-secure until clamd's DB finishes downloading).
    send_argv = [
        "compose",
        "exec",
        "-T",
        "stalwart",
        "curl",
        "-sS",
        "--url",
        "smtps://localhost:465",
        "--mail-from",
        f"alice@{DOMAIN}",
        "--mail-rcpt",
        f"bob@{DOMAIN}",
        "--upload-file",
        "/tmp/e2e_msg.txt",
        "--user",
        f"alice@{DOMAIN}:{ALICE_PW}",
        "-k",
    ]
    send = None
    for _ in range(20):
        send = _sh(send_argv)
        if send.returncode == 0:
            break
        time.sleep(6)
    if send is None or send.returncode != 0:
        _cleanup(admin, domain_id, account_ids)
        sys.exit(
            f"FAIL: SMTP submission failed after retries: {send.stderr[:300] if send else 'no attempt'}"
        )

    # 4. Confirm receipt in bob's mailbox via JMAP (poll for delivery).
    found = False
    for _ in range(20):
        q = _jmap(
            f"bob@{DOMAIN}:{BOB_PW}",
            [
                ["Email/query", {"accountId": account_ids[1]}, "c0"],
                [
                    "Email/get",
                    {
                        "accountId": account_ids[1],
                        "#ids": {
                            "resultOf": "c0",
                            "name": "Email/query",
                            "path": "/ids",
                        },
                        "properties": ["subject"],
                    },
                    "c1",
                ],
            ],
            using=["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
        )
        emails = q["methodResponses"][1][1].get("list", [])
        if any(e.get("subject") == subject for e in emails):
            found = True
            break
        time.sleep(1.5)

    _cleanup(admin, domain_id, account_ids)
    if not found:
        sys.exit("FAIL: message was sent but never arrived in bob's mailbox")
    print(f"PASS: Stalwart delivered alice->bob ({subject!r}) over SMTP+IMAP/JMAP")
    return 0


def _cleanup(admin: str, domain_id: str, account_ids: list[str]) -> None:
    if account_ids:
        _jmap(admin, [["x:Account/set", {"destroy": account_ids}, "c0"]])
    if domain_id:
        _jmap(admin, [["x:Domain/set", {"destroy": [domain_id]}, "c0"]])


if __name__ == "__main__":
    sys.exit(main())
