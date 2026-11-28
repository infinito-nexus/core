from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import unittest.mock as mock
import urllib.parse
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.serialization import Encoding

from tests.utils.connect_proxy import ConnectProxy, direct_dials, recorded_dials
from tests.utils.openbao_stub import OpenBaoStub, make_ca
from utils.openbao_client import https_connection

from ._export_servers import HttpsApp, SmtpRelay, load_task_module, server_context

WORKSPACE = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
OWNER = "11111111-2222-4333-8444-555555555555"
STRANGER = "99999999-8888-4777-8666-555555555555"
ORG = "o-1"
GROUP = "g-owner"
JWT = "task-jwt"
BAO_TOKEN = "s.export"
KEYCLOAK_RECIPIENT = "age1" + "q" * 58
PLANTED_RECIPIENT = "age1" + "p" * 58
VALUE = "tenant-secret-4711"
CLIENT_SECRET = "export-client-secret"
RELAY_PASSWORD = "relay-password-0815"
DAY_MS = 86_400_000
FAKE_KEEPASSXC = """
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
xml = Path(args[2])
entry = {"tool": "keepassxc-cli", "args": args, "stdin": sys.stdin.read(),
         "mode": xml.stat().st_mode & 0o777, "xml": xml.read_text()}
with open(os.environ["FAKE_EXPORT_LOG"], "a") as handle:
    handle.write(json.dumps(entry) + "\\n")
Path(args[3]).write_bytes(b"kdbx")
"""
FAKE_AGE = """
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
stdin = sys.stdin.read()
with open(os.environ["FAKE_EXPORT_LOG"], "a") as handle:
    handle.write(json.dumps({"tool": "age", "args": args, "stdin": stdin}) + "\\n")
Path(args[args.index("-o") + 1]).write_text("sealed")
"""


export = load_task_module("export")
task = load_task_module("export_task")


def membership(operation: str, age_days: float) -> dict[str, Any]:
    return {
        "resourceType": task.MEMBERSHIP_TYPE,
        "resourcePath": export.membership_path(ORG, GROUP, OWNER),
        "operationType": operation,
        "time": int(time.time() * 1000 - age_days * DAY_MS),
    }


def argv_findings(tools: list[dict[str, Any]], workdir: Path) -> list[str]:
    """
    Args:
        tools: the calls the fake tools logged, as ``ExportCase.tools`` reads them.
        workdir: the directory ``build_archive`` worked in.

    Returns:
        Each tool whose arguments are anything but its file paths and the
        recipient, by name and never by an argument value.
    """
    expected = {
        "keepassxc-cli": [
            "import",
            "--set-password",
            str(workdir / "secrets.xml"),
            str(workdir / "secrets.kdbx"),
        ],
        "age": ["-r", KEYCLOAK_RECIPIENT, "-o", str(workdir / "passphrase.age")],
    }
    ran = sorted(entry["tool"] for entry in tools)
    if ran != sorted(expected):
        return [f"the tools that ran are {ran}"]
    return [
        f"{entry['tool']} takes other arguments than its paths and the recipient"
        for entry in tools
        if entry["args"] != expected[entry["tool"]]
    ]


class Keycloak:
    """
    Args:
        members: the direct members of the pinned group.
        attributes: the attributes of ``OWNER``.
        events: the admin events the realm keeps.
    """

    def __init__(
        self,
        members: list[str],
        attributes: dict[str, list[str]],
        events: list[dict[str, Any]],
    ) -> None:
        self.members = members
        self.attributes = attributes
        self.events = events
        self.uploads: list[bytes] = []

    def __call__(
        self, method: str, url: str, body: bytes | None, headers: Any
    ) -> tuple[int, bytes]:
        path = urllib.parse.urlsplit(url).path
        admin = "/admin/realms/infinito/"
        answers = {
            ("POST", "/realms/infinito/protocol/openid-connect/token"): {
                "access_token": "kc-token"
            },
            ("GET", f"{admin}organizations"): [{"id": ORG}],
            ("GET", f"{admin}organizations/{ORG}/groups/{GROUP}/members"): [
                {"id": member, "email": f"{member}@example.org"}
                for member in self.members
            ],
            ("GET", f"{admin}users/{OWNER}"): {
                "id": OWNER,
                "attributes": self.attributes,
            },
            ("GET", f"{admin}admin-events"): self.events,
        }
        if method == "PUT" and path == f"/exports/ws-{WORKSPACE}/42.tar":
            self.uploads.append(body or b"")
            return 200, b""
        if (method, path) not in answers:
            return 404, b"{}"
        return 200, json.dumps(answers[(method, path)]).encode()


class ExportCase(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = OpenBaoStub(
            tokens={BAO_TOKEN: ["platform/export/", f"tenant/ws-{WORKSPACE}/"]},
            logins={(f"ws-{WORKSPACE}", JWT): BAO_TOKEN},
        )
        self.addCleanup(self.stub.close)
        self.stub.put(
            "platform/export/keycloak",
            {"client_id": "export", "client_secret": CLIENT_SECRET},
        )
        self.stub.put(f"platform/export/owners/ws-{WORKSPACE}", {"group": GROUP})
        self.stub.put("platform/export/s3", {"access_key": "AK", "secret_key": "SK"})
        self.stub.put(f"tenant/ws-{WORKSPACE}/db/app", {"password": VALUE})
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        for name, source in (("keepassxc-cli", FAKE_KEEPASSXC), ("age", FAKE_AGE)):
            tool = bin_dir / name
            tool.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
            tool.chmod(0o755)
        self.log = self.root / "tools.jsonl"
        patched = mock.patch.dict(
            os.environ,
            {
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "FAKE_EXPORT_LOG": str(self.log),
            },
        )
        patched.start()
        self.addCleanup(patched.stop)
        smtp = mock.patch.object(export.smtplib, "SMTP")
        self.smtp = smtp.start()
        self.addCleanup(smtp.stop)
        smtp_ssl = mock.patch.object(export.smtplib, "SMTP_SSL")
        self.smtp_ssl = smtp_ssl.start()
        self.addCleanup(smtp_ssl.stop)
        self.stub.put(
            "platform/export/mail",
            {"username": "no-reply@example.org", "password": RELAY_PASSWORD},
        )
        self.env = {
            "WORKSPACE": WORKSPACE,
            "EXPORT_FOR": OWNER,
            "SEMAPHORE_JWT": JWT,
            "SEMAPHORE_TASK_ID": "42",
            "BAO_ADDR": self.stub.addr,
            "BAO_CACERT": self.stub.cafile,
            "EXPORT_KEYCLOAK_URL": "https://auth.example.org",
            "EXPORT_KEYCLOAK_REALM": "infinito",
            "EXPORT_S3_ENDPOINT": "https://s3.example.org",
            "EXPORT_S3_REGION": "us-east-1",
            "EXPORT_MAIL_HOST": "mail.example.org",
            "EXPORT_MAIL_PORT": "587",
            "EXPORT_MAIL_FROM": "export@example.org",
            "EXPORT_MAIL_TLS": "false",
            "EXPORT_MAIL_AUTH": "false",
            "EXPORT_OWNER_MIN_AGE_DAYS": "7",
            "EXPORT_RECIPIENT": PLANTED_RECIPIENT,
            "AGE_RECIPIENT": PLANTED_RECIPIENT,
            "RECIPIENT": PLANTED_RECIPIENT,
        }

    def keycloak(self, **changes: Any) -> Keycloak:
        values = {
            "members": [OWNER],
            "attributes": {export.RECIPIENT_ATTRIBUTE: [KEYCLOAK_RECIPIENT]},
            "events": [membership("CREATE", 30)],
        }
        values.update(changes)
        return Keycloak(**values)

    def tools(self) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        text = self.log.read_text()  # nocheck: cache-read tempdir
        return [json.loads(line) for line in text.splitlines()]

    def mails(self) -> list[str]:
        sent = self.smtp.return_value.__enter__.return_value.send_message
        return [call.args[0].get_content() for call in sent.call_args_list]

    def tenant_reads(self) -> list[str]:
        return [path for _, path, _ in self.stub.requests if path.startswith("tenant/")]


class TestExport(ExportCase):
    def test_export_sh_takes_the_recipient_from_keycloak_only(self) -> None:
        workdir = self.root / "task"
        workdir.mkdir()
        keycloak = self.keycloak()
        link = export.run(self.env, keycloak, workdir)
        age = [entry for entry in self.tools() if entry["tool"] == "age"]
        self.assertEqual(len(age), 1)
        self.assertEqual(age[0]["args"][:2], ["-r", KEYCLOAK_RECIPIENT])
        self.assertNotIn(PLANTED_RECIPIENT, json.dumps(self.tools()))
        self.assertIn("X-Amz-Signature=", link)
        self.assertIn("X-Amz-Expires=900", link)

    def test_the_archive_holds_the_database_and_the_sealed_passphrase(self) -> None:
        workdir = self.root / "task"
        workdir.mkdir()
        keycloak = self.keycloak()
        export.run(self.env, keycloak, workdir)
        with tarfile.open(fileobj=io.BytesIO(keycloak.uploads[0])) as tar:
            self.assertEqual(sorted(tar.getnames()), ["passphrase.age", "secrets.kdbx"])
        keepass, age = self.tools()
        passphrase = age["stdin"]
        self.assertEqual(len(passphrase), 64)
        self.assertEqual(keepass["stdin"], f"{passphrase}\n{passphrase}\n")
        self.assertEqual(keepass["mode"], 0o600)
        self.assertIn(VALUE, keepass["xml"])
        argv = json.dumps([keepass["args"], age["args"]])
        self.assertNotIn(passphrase, argv)
        self.assertNotIn(VALUE, argv)
        self.assertEqual(list(workdir.iterdir()), [])
        self.assertEqual(len(self.mails()), 1)

    def test_the_tools_take_only_paths_and_the_recipient_as_arguments(self) -> None:
        workdir = self.root / "argv"
        workdir.mkdir()
        export.run(self.env, self.keycloak(), workdir)
        self.assertEqual(argv_findings(self.tools(), workdir), [])

    def test_negative_control_a_passphrase_argument_is_found(self) -> None:
        workdir = self.root / "argv-planted"
        workdir.mkdir()
        real_run = subprocess.run

        def leaky(argv: list[str], **kwargs: Any) -> Any:
            if argv[0] == "age":
                argv = [*argv, kwargs["input"]]
            return real_run(argv, **kwargs)

        with mock.patch.object(export.subprocess, "run", leaky):
            export.run(self.env, self.keycloak(), workdir)
        self.assertEqual(
            argv_findings(self.tools(), workdir),
            ["age takes other arguments than its paths and the recipient"],
        )

    def test_a_refusal_reads_no_tenant_secret_and_tells_every_owner(self) -> None:
        cases = {
            "no direct member": self.keycloak(members=[STRANGER]),
            "no recipient": self.keycloak(attributes={}),
            "a planted recipient only": self.keycloak(
                attributes={"other": [KEYCLOAK_RECIPIENT]}
            ),
            "joined a minute ago": self.keycloak(
                events=[membership("CREATE", 1 / 1440)]
            ),
        }
        for name, keycloak in cases.items():
            with self.subTest(case=name):
                self.stub.requests.clear()
                self.smtp.reset_mock()
                workdir = self.root / name.replace(" ", "-")
                workdir.mkdir()
                with self.assertRaises(export.ExportRefusedError):
                    export.run(self.env, keycloak, workdir)
                self.assertEqual(self.tenant_reads(), [])
                self.assertEqual(self.tools(), [])
                self.assertEqual(keycloak.uploads, [])
                self.assertEqual(len(self.mails()), 1)
                self.assertIn("Refused:", self.mails()[0])

    def test_the_relay_transport_follows_the_platform_mail_settings(self) -> None:
        cases = {
            ("false", "false"): (self.smtp, self.smtp_ssl, False),
            ("false", "true"): (self.smtp, self.smtp_ssl, True),
            ("true", "false"): (self.smtp_ssl, self.smtp, False),
            ("true", "true"): (self.smtp_ssl, self.smtp, True),
        }
        for (tls, auth), (used, unused, logs_in) in cases.items():
            with self.subTest(tls=tls, auth=auth):
                self.smtp.reset_mock()
                self.smtp_ssl.reset_mock()
                workdir = self.root / f"tls-{tls}-auth-{auth}"
                workdir.mkdir()
                env = {**self.env, "EXPORT_MAIL_TLS": tls, "EXPORT_MAIL_AUTH": auth}
                export.run(env, self.keycloak(), workdir)
                session = used.return_value.__enter__.return_value
                self.assertEqual(unused.call_count, 0)
                self.assertEqual(session.starttls.call_count, 0)
                self.assertEqual(session.send_message.call_count, 1)
                self.assertEqual(
                    session.login.call_args_list,
                    [mock.call("no-reply@example.org", RELAY_PASSWORD)]
                    if logs_in
                    else [],
                )
                if tls == "true":
                    self.assertIn("context", used.call_args.kwargs)

    def test_a_malformed_mail_flag_is_refused_before_any_request(self) -> None:
        for name in task.MAIL_FLAGS:
            with self.subTest(name=name):
                self.stub.requests.clear()
                workdir = self.root / f"malformed-{name}"
                workdir.mkdir()
                with self.assertRaisesRegex(export.ExportRefusedError, name):
                    export.run({**self.env, name: "yes"}, self.keycloak(), workdir)
                self.assertEqual(self.stub.requests, [])


class TestTheXmlLifetime(ExportCase):
    def xml_findings(self, name: str, failing: bool) -> list[str]:
        """
        Args:
            name: the task directory below the scratch root.
            failing: whether ``keepassxc-cli`` exits non-zero.

        Returns:
            How ``secrets.xml`` outlives its import in ``build_archive``: the
            import ran without it, ``age`` ran beside it, or it is left behind.
        """
        workdir = self.root / name
        workdir.mkdir()
        xml = workdir / "secrets.xml"
        seen: list[tuple[str, bool]] = []
        real_run = subprocess.run

        def run(argv: list[str], **kwargs: Any) -> Any:
            seen.append((argv[0], xml.exists()))
            if failing and argv[0] == "keepassxc-cli":
                argv = [sys.executable, "-c", "raise SystemExit(1)"]
            return real_run(argv, **kwargs)

        entries = {"db/app": {"password": VALUE}}
        with mock.patch.object(export.subprocess, "run", run):
            if failing:
                with self.assertRaises(subprocess.CalledProcessError):
                    export.build_archive(entries, KEYCLOAK_RECIPIENT, workdir)
            else:
                export.build_archive(entries, KEYCLOAK_RECIPIENT, workdir)
        findings: list[str] = []
        if seen[:1] != [("keepassxc-cli", True)]:
            findings.append("the import ran without the xml")
        if ("age", True) in seen:
            findings.append("age ran beside the xml")
        if xml.exists():
            findings.append("the xml outlives build_archive")
        return findings

    def test_the_xml_is_gone_before_age_runs(self) -> None:
        self.assertEqual(self.xml_findings("sealed", failing=False), [])

    def test_a_failed_import_leaves_no_xml(self) -> None:
        self.assertEqual(self.xml_findings("failed", failing=True), [])

    def test_negative_control_a_kept_xml_is_found(self) -> None:
        real_unlink = export.Path.unlink

        def keep_xml(path: Path, **kwargs: Any) -> None:
            if path.name != "secrets.xml":
                real_unlink(path, **kwargs)

        with mock.patch.object(export.Path, "unlink", keep_xml):
            sealed = self.xml_findings("kept-sealed", failing=False)
            failed = self.xml_findings("kept-failed", failing=True)
        self.assertEqual(
            sealed, ["age ran beside the xml", "the xml outlives build_archive"]
        )
        self.assertEqual(failed, ["the xml outlives build_archive"])


class TestExportBehindTheEgressProxy(ExportCase):
    def setUp(self) -> None:
        super().setUp()
        ca_key, ca_cert = make_ca("export test CA")
        self.bundle = self.root / "bundle.pem"
        self.bundle.write_bytes(
            Path(self.stub.cafile).read_bytes()  # nocheck: cache-read tempdir
            + ca_cert.public_bytes(Encoding.PEM)
        )
        context = server_context(self.root, ca_key, ca_cert)
        self.kc = self.keycloak()
        self.web = HttpsApp(self.kc, context)
        self.addCleanup(self.web.close)
        self.relays = {"false": SmtpRelay(None), "true": SmtpRelay(context)}
        for relay in self.relays.values():
            self.addCleanup(relay.close)
        self.proxy = ConnectProxy()
        self.addCleanup(self.proxy.close)
        self.bao_target = self.stub.addr.removeprefix("https://")

    def export_env(self, tls: str, proxy: str | None) -> dict[str, str]:
        env = {
            **self.env,
            "BAO_CACERT": str(self.bundle),
            "EXPORT_KEYCLOAK_URL": f"https://{self.web.target}",
            "EXPORT_S3_ENDPOINT": f"https://{self.web.target}",
            "EXPORT_MAIL_HOST": "127.0.0.1",
            "EXPORT_MAIL_PORT": str(self.relays[tls].port),
            "EXPORT_MAIL_TLS": tls,
        }
        if proxy:
            env[task.PROXY_ENV] = proxy
        return env

    def run_export(self, env: dict[str, str], name: str) -> tuple[str, list[str]]:
        """
        Args:
            env: see ``export_env``.
            name: the task directory below the scratch root.

        Returns:
            The link and every dial of the run, with the opener ``main`` builds.
        """
        workdir = self.root / name
        workdir.mkdir()
        opener = export.task_opener(env)
        with recorded_dials() as dials:
            link = export.run(env, opener, workdir)
        return link, dials

    def test_openbao_keycloak_s3_and_the_relay_go_through_the_tunnel(self) -> None:
        for tls, relay in self.relays.items():
            with self.subTest(tls=tls):
                self.proxy.targets.clear()
                self.kc.uploads.clear()
                env = self.export_env(tls, self.proxy.address)
                link, dials = self.run_export(env, f"proxied-{tls}")
                self.assertIn("X-Amz-Signature=", link)
                self.assertEqual(direct_dials(dials, self.proxy.address), [])
                self.assertEqual(
                    set(self.proxy.targets),
                    {self.bao_target, self.web.target, relay.target},
                )
                self.assertEqual(len(self.kc.uploads), 1)
                self.assertEqual(len(relay.messages), 1)
                self.assertIn("An export of the workspace secrets", relay.messages[0])
                self.assertEqual(self.smtp.call_count + self.smtp_ssl.call_count, 0)
        self.assertTrue(self.tenant_reads())

    def test_without_the_proxy_every_connection_is_direct(self) -> None:
        env = self.export_env("false", None)
        link, dials = self.run_export(env, "direct")
        self.assertIn("X-Amz-Signature=", link)
        self.assertEqual(self.proxy.targets, [])
        self.assertEqual(set(dials), {self.bao_target, self.web.target})
        self.assertEqual(
            self.smtp.call_args.args, ("127.0.0.1", self.relays["false"].port)
        )
        self.assertEqual(self.relays["false"].messages, [])

    def test_negative_control_a_direct_https_request_beside_the_proxy_is_found(
        self,
    ) -> None:
        def direct(host, port, context, timeout, proxy=None):
            return https_connection(host, port, context, timeout)

        env = self.export_env("false", self.proxy.address)
        with mock.patch.object(task, "https_connection", direct):
            _, dials = self.run_export(env, "planted-https")
        self.assertNotIn(self.web.target, self.proxy.targets)
        self.assertEqual(
            set(direct_dials(dials, self.proxy.address)), {self.web.target}
        )

    def test_negative_control_a_direct_relay_session_beside_the_proxy_is_found(
        self,
    ) -> None:
        plain = task.TunneledSMTP.__mro__[1]

        def direct(proxy, host, port, context):
            return plain(host, port)

        env = self.export_env("false", self.proxy.address)
        with mock.patch.object(task, "TunneledSMTP", direct):
            _, dials = self.run_export(env, "planted-smtp")
        self.assertNotIn(self.relays["false"].target, self.proxy.targets)
        self.assertEqual(
            direct_dials(dials, self.proxy.address), [self.relays["false"].target]
        )


GATE_CASES = (
    ("a young CREATE", [membership("CREATE", 1)], True),
    ("an old CREATE", [membership("CREATE", 30)], False),
    ("no event", [], False),
    (
        "a CREATE after a DELETE",
        [
            membership("CREATE", 60),
            membership("DELETE", 2),
            membership("CREATE", 1),
        ],
        True,
    ),
    ("an old DELETE last", [membership("CREATE", 60), membership("DELETE", 30)], False),
)


def gate_findings() -> list[str]:
    path = export.membership_path(ORG, GROUP, OWNER)
    now_ms = int(time.time() * 1000)
    shuffled = {name: list(reversed(events)) for name, events, _ in GATE_CASES}
    return [
        name
        for name, events, refused in GATE_CASES
        for ordering in (events, shuffled[name])
        if (export.age_refusal(ordering, path, now_ms, 7) is not None) != refused
    ]


class TestTheAgeGate(unittest.TestCase):
    def test_the_age_gate_reads_the_newest_membership_event(self) -> None:
        self.assertEqual(gate_findings(), [])

    def test_control_a_gate_that_reads_the_oldest_event_fails(self) -> None:
        def oldest(events: list[dict[str, Any]], path: str) -> Any:
            matching = [event for event in events if event["resourcePath"] == path]
            return min(matching, key=lambda event: event["time"], default=None)

        with mock.patch.object(task, "newest_membership", oldest):
            self.assertNotEqual(gate_findings(), [])

    def test_an_event_of_another_member_does_not_count(self) -> None:
        foreign = dict(membership("CREATE", 1), resourcePath="organizations/o-1/x")
        self.assertIsNone(
            export.age_refusal(
                [foreign],
                export.membership_path(ORG, GROUP, OWNER),
                int(time.time() * 1000),
                7,
            )
        )


if __name__ == "__main__":
    unittest.main()
