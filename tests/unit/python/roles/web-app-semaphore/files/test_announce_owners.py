from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path
from typing import Any
from unittest import mock

from cryptography.hazmat.primitives.serialization import Encoding

from tests.utils.connect_proxy import ConnectProxy, direct_dials, recorded_dials
from tests.utils.openbao_stub import OpenBaoStub, make_ca
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.openbao_client import https_connection
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from ._export_servers import HttpsApp, SmtpRelay, load_task_module, server_context

announce = load_task_module("announce_owners")
task = load_task_module("export_task")

WS_A = "0a000000-0000-4000-8000-000000000001"
WS_B = "0b000000-0000-4000-8000-000000000002"
OWNER = "11111111-1111-4111-8111-111111111111"
NEWBIE = "22222222-2222-4222-8222-222222222222"
SUB = "33333333-3333-4333-8333-333333333333"
RENAMED = "44444444-4444-4444-8444-444444444444"
OWNER_B = "55555555-5555-4555-8555-555555555555"
NEWBIE_B = "66666666-6666-4666-8666-666666666666"
JWT = "announce-task-jwt"
BAO_TOKEN = "s.announce"
CLIENT_SECRET = "export-client-secret-4711"
RELAY_PASSWORD = "relay-password-0815"
DAY_MS = 86_400_000
GROUPS = {
    ("o-a", "g-a"): [OWNER, NEWBIE],
    ("o-a", "g-sub"): [SUB],
    ("o-a", "g-renamed"): [RENAMED],
    ("o-b", "g-b"): [OWNER_B, NEWBIE_B],
}


def membership(
    organization: str, group: str, user: str, operation: str, at_ms: int
) -> dict[str, Any]:
    return {
        "resourceType": task.MEMBERSHIP_TYPE,
        "resourcePath": task.membership_path(organization, group, user),
        "operationType": operation,
        "time": at_ms,
    }


class Realm:
    """
    Args:
        now: the time of the run in epoch milliseconds.
        markers: per workspace id, the organizations carrying its marker.
    """

    def __init__(self, now: int, markers: dict[str, list[str]]) -> None:
        self.markers = markers
        self.joined = now - DAY_MS
        self.events = [
            membership("o-a", "g-a", OWNER, "CREATE", now - 30 * DAY_MS),
            membership("o-a", "g-a", NEWBIE, "CREATE", self.joined),
            membership("o-a", "g-sub", SUB, "CREATE", self.joined),
            membership("o-a", "g-renamed", RENAMED, "CREATE", self.joined),
            membership("o-b", "g-b", OWNER_B, "CREATE", now - 60 * DAY_MS),
            membership("o-b", "g-b", NEWBIE_B, "DELETE", now - 3 * DAY_MS),
            membership("o-b", "g-b", NEWBIE_B, "CREATE", self.joined),
        ]

    def __call__(
        self, method: str, url: str, body: bytes | None, headers: Any
    ) -> tuple[int, bytes]:
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query))
        admin = "/admin/realms/infinito/"
        if (method, parts.path) == (
            "POST",
            "/realms/infinito/protocol/openid-connect/token",
        ):
            return 200, json.dumps({"access_token": "kc-token"}).encode()
        path = parts.path.removeprefix(admin)
        if path == "organizations":
            workspace = query["q"].removeprefix("workspace.id:")
            found = [{"id": org} for org in self.markers.get(workspace, [])]
            return 200, json.dumps(found).encode()
        if path == "admin-events":
            matching = [
                e for e in self.events if e["resourcePath"] == query["resourcePath"]
            ]
            return 200, json.dumps(matching).encode()
        segments = path.split("/")
        if len(segments) == 5 and segments[0] == "organizations":
            members = GROUPS.get((segments[1], segments[3]), [])
            answer = [
                {"id": m, "username": f"user-{m[:4]}", "email": f"{m[:4]}@example.org"}
                for m in members
            ]
            return 200, json.dumps(answer).encode()
        return 404, b"{}"


class AnnounceCase(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = OpenBaoStub(
            tokens={BAO_TOKEN: ["platform/export/"]},
            logins={(announce.ROLE, JWT): BAO_TOKEN},
        )
        self.addCleanup(self.stub.close)
        self.stub.put(
            "platform/export/keycloak",
            {"client_id": "export", "client_secret": CLIENT_SECRET},
        )
        self.stub.put(f"platform/export/owners/ws-{WS_A}", {"group": "g-a"})
        self.stub.put(f"platform/export/owners/ws-{WS_B}", {"group": "g-b"})
        self.stub.put(
            "platform/export/mail",
            {"username": "no-reply@example.org", "password": RELAY_PASSWORD},
        )
        self.stub.put(f"tenant/ws-{WS_A}/db/app", {"password": "tenant-secret"})
        smtp = mock.patch.object(task.smtplib, "SMTP")
        self.smtp = smtp.start()
        self.addCleanup(smtp.stop)
        self.now = int(time.time() * 1000)
        self.realm = Realm(self.now, {WS_A: ["o-a"], WS_B: ["o-b"]})
        self.env = {
            "SEMAPHORE_JWT": JWT,
            "BAO_ADDR": self.stub.addr,
            "BAO_CACERT": self.stub.cafile,
            "EXPORT_KEYCLOAK_URL": "https://auth.example.org",
            "EXPORT_KEYCLOAK_REALM": "infinito",
            "EXPORT_MAIL_HOST": "mail.example.org",
            "EXPORT_MAIL_PORT": "587",
            "EXPORT_MAIL_FROM": "export@example.org",
            "EXPORT_MAIL_TLS": "false",
            "EXPORT_MAIL_AUTH": "true",
            "EXPORT_OWNER_MIN_AGE_DAYS": "7",
        }

    def run_announce(self, now: int | None = None) -> tuple[list[str], list[str]]:
        return announce.run(self.env, self.realm, self.now if now is None else now)

    def mails(self) -> list[tuple[str, str, str]]:
        sent = self.smtp.return_value.__enter__.return_value.send_message
        return [
            (c.args[0]["To"], c.args[0]["Subject"], c.args[0].get_content())
            for c in sent.call_args_list
        ]


def addresses(*users: str) -> str:
    return ", ".join(f"{user[:4]}@example.org" for user in users)


class TestTheAnnouncement(AnnounceCase):
    def test_a_new_owner_is_announced_to_every_direct_member(self) -> None:
        announced, failures = self.run_announce()
        self.assertEqual(failures, [])
        self.assertEqual(
            announced,
            [f"ws-{WS_A}: announced {NEWBIE}", f"ws-{WS_B}: announced {NEWBIE_B}"],
        )
        (to_a, subject_a, text_a), (to_b, _, _) = self.mails()
        self.assertEqual(to_a, addresses(OWNER, NEWBIE))
        self.assertEqual(to_b, addresses(OWNER_B, NEWBIE_B))
        self.assertEqual(subject_a, f"New Owner of workspace ws-{WS_A}")
        self.assertIn(f"New Owner: user-2222 <2222@example.org> ({NEWBIE})", text_a)
        self.assertIn(f"Joined: {task.iso(self.realm.joined)}", text_a)
        self.assertIn(
            f"First export possible: {task.iso(self.realm.joined + 7 * DAY_MS)}",
            text_a,
        )
        session = self.smtp.return_value.__enter__.return_value
        self.assertEqual(
            session.login.call_args_list[0],
            mock.call("no-reply@example.org", RELAY_PASSWORD),
        )
        self.assertFalse(
            [p for _, p, _ in self.stub.requests if p.startswith("tenant/")]
        )

    def test_a_second_run_without_a_change_mails_again(self) -> None:
        self.run_announce()
        first = self.mails()
        self.run_announce()
        self.assertEqual(self.mails(), first + first)

    def test_a_run_after_the_window_mails_nothing(self) -> None:
        after = self.realm.joined + 7 * DAY_MS + 60_000
        self.assertEqual(self.run_announce(after), ([], []))
        self.assertEqual(self.mails(), [])
        just_inside = self.realm.joined + 7 * DAY_MS - 60_000
        self.assertEqual(len(self.run_announce(just_inside)[0]), 2)

    def test_a_subgroup_or_renamed_group_member_never_counts(self) -> None:
        self.run_announce()
        text = json.dumps(self.mails())
        for user in (SUB, RENAMED):
            with self.subTest(user=user):
                self.assertNotIn(user, text)

    def test_control_an_announcer_that_reads_another_group_names_its_members(
        self,
    ) -> None:
        for group, user in (("g-sub", SUB), ("g-renamed", RENAMED)):
            with self.subTest(group=group):
                self.smtp.reset_mock()
                found = mock.patch.object(
                    announce.Announcer,
                    "pinned_group",
                    lambda _self, record, group=group: (WS_A, group),
                )
                with found:
                    self.run_announce()
                self.assertIn(user, json.dumps(self.mails()))

    def test_one_failing_workspace_does_not_hide_the_others(self) -> None:
        self.realm.markers[WS_A] = ["o-a", "o-x"]
        announced, failures = self.run_announce()
        self.assertEqual(
            failures,
            [f"ws-{WS_A}: no single organization carries the workspace marker"],
        )
        self.assertEqual(announced, [f"ws-{WS_B}: announced {NEWBIE_B}"])
        self.assertEqual(len(self.mails()), 1)

    def test_control_without_the_per_workspace_catch_the_others_stay_unmailed(
        self,
    ) -> None:
        self.realm.markers[WS_A] = ["o-a", "o-x"]
        with (
            mock.patch.object(announce, "FAILURES", ()),
            self.assertRaises(task.ExportRefusedError),
        ):
            self.run_announce()
        self.assertEqual(self.mails(), [])

    def test_main_names_every_failed_workspace_and_exits_non_zero(self) -> None:
        self.realm.markers[WS_A] = []
        code, stdout, stderr = self.main()
        self.assertEqual(code, 1)
        self.assertIn(
            f"announce owners failed: ws-{WS_A}: no single organization", stderr
        )
        self.assertIn(f"ws-{WS_B}: announced {NEWBIE_B}", stdout)

    def test_no_secret_reaches_the_output(self) -> None:
        code, stdout, stderr = self.main()
        self.assertEqual(code, 0, stderr)
        for secret in (CLIENT_SECRET, RELAY_PASSWORD, JWT, BAO_TOKEN, "kc-token"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, stdout + stderr)

    def main(self) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.dict(os.environ, self.env),
            mock.patch.object(announce, "task_opener", lambda environ: self.realm),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = announce.main([])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_the_environment_of_the_scheduled_templates_supplies_every_name(
        self,
    ) -> None:
        variables = load_yaml_any(
            str(PROJECT_ROOT / "roles/web-app-semaphore" / ROLE_FILE_VARS_MAIN)
        )["SEMAPHORE_EXPORT_VARIABLES"]
        self.assertEqual(
            sorted(set(announce.REQUIRED_ENV) - set(variables)), ["SEMAPHORE_JWT"]
        )

    def test_a_missing_or_malformed_value_is_refused_before_any_request(self) -> None:
        for name, value in (
            ("EXPORT_OWNER_MIN_AGE_DAYS", ""),
            ("EXPORT_MAIL_AUTH", "yes"),
        ):
            with self.subTest(name=name):
                self.stub.requests.clear()
                with self.assertRaisesRegex(task.ExportRefusedError, name):
                    announce.run({**self.env, name: value}, self.realm, self.now)
                self.assertEqual(self.stub.requests, [])


class TestTheAnnouncementBehindTheEgressProxy(AnnounceCase):
    def setUp(self) -> None:
        super().setUp()
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        ca_key, ca_cert = make_ca("announce test CA")
        self.bundle = directory / "bundle.pem"
        self.bundle.write_bytes(
            Path(self.stub.cafile).read_bytes()  # nocheck: cache-read tempdir
            + ca_cert.public_bytes(Encoding.PEM)
        )
        context = server_context(directory, ca_key, ca_cert)
        self.web = HttpsApp(self.realm, context)
        self.addCleanup(self.web.close)
        self.relay = SmtpRelay(None)
        self.addCleanup(self.relay.close)
        self.proxy = ConnectProxy()
        self.addCleanup(self.proxy.close)
        self.env.update(
            {
                "BAO_CACERT": str(self.bundle),
                "EXPORT_KEYCLOAK_URL": f"https://{self.web.target}",
                "EXPORT_MAIL_HOST": "127.0.0.1",
                "EXPORT_MAIL_PORT": str(self.relay.port),
                "EXPORT_MAIL_AUTH": "false",
                task.PROXY_ENV: self.proxy.address,
            }
        )

    def proxied_run(self) -> list[str]:
        with recorded_dials() as dials:
            announce.run(self.env, task.task_opener(self.env), self.now)
        return dials

    def test_openbao_keycloak_and_the_relay_go_through_the_tunnel(self) -> None:
        dials = self.proxied_run()
        self.assertEqual(direct_dials(dials, self.proxy.address), [])
        self.assertEqual(
            set(self.proxy.targets),
            {
                self.stub.addr.removeprefix("https://"),
                self.web.target,
                self.relay.target,
            },
        )
        self.assertEqual(len(self.relay.messages), 2)
        self.assertEqual(self.smtp.call_count, 0)

    def test_negative_control_a_direct_https_request_beside_the_proxy_is_found(
        self,
    ) -> None:
        def direct(host, port, context, timeout, proxy=None):
            return https_connection(host, port, context, timeout)

        with mock.patch.object(task, "https_connection", direct):
            dials = self.proxied_run()
        self.assertEqual(
            set(direct_dials(dials, self.proxy.address)), {self.web.target}
        )


if __name__ == "__main__":
    unittest.main()
