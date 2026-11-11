import contextlib
import importlib.util
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from . import PROJECT_ROOT

SCRIPTS = PROJECT_ROOT / "roles/web-app-stalwart/files/python"
LIST_LINES = [
    b'(\\HasNoChildren) "/" "INBOX"',
    b'(\\HasNoChildren \\Sent) "/" "Sent Items"',
    b'(\\HasNoChildren \\Junk) "/" "Junk Mail"',
    b'(\\HasNoChildren) "/" Archive',
]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, str(SCRIPTS / f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_module():
    _load("mailu_maildir")
    _load("imap_layout")
    return _load("migrate_from_mailu")


def _unquote(name: str) -> str:
    return name[1:-1] if name.startswith('"') else name


class _FakeImap:
    def __init__(self, existing_headers: list[bytes] | None = None, list_lines=None):
        self.created: list[str] = []
        self.selected: list[str] = []
        self.appended: list[tuple[str, str | None, str, bytes]] = []
        self._existing_headers = existing_headers or []
        self._list_lines = LIST_LINES if list_lines is None else list_lines

    def list(self):
        return "OK", list(self._list_lines)

    def create(self, mailbox):
        self.created.append(_unquote(mailbox))
        return "OK", [b""]

    def select(self, mailbox, readonly=False):
        self.selected.append(_unquote(mailbox))
        return "OK", [str(len(self._existing_headers)).encode()]

    def search(self, charset, *criteria):
        nums = b" ".join(
            str(i + 1).encode() for i in range(len(self._existing_headers))
        )
        return "OK", [nums]

    def fetch(self, message_set, message_parts):
        data = [
            ((f"{i + 1} ()").encode(), header)
            for i, header in enumerate(self._existing_headers)
        ]
        return "OK", data

    def append(self, mailbox, flags, date_time, message):
        self.appended.append((_unquote(mailbox), flags, date_time, message))
        return "OK", [b""]


class _SlowImap(_FakeImap):
    """A session that waits for its siblings before it appends anything.

    `ThreadPoolExecutor` promises a thread count, never that every worker
    receives an item from a shared iterator, so counting the sessions that
    happened to append is a race rather than a check.
    """

    def __init__(self, barrier=None, **kwargs):
        super().__init__(**kwargs)
        self._barrier = barrier
        self._waited = False

    def append(self, mailbox, flags, date_time, message):
        if self._barrier is not None and not self._waited:
            self._waited = True
            with contextlib.suppress(threading.BrokenBarrierError):
                self._barrier.wait(timeout=10)
        time.sleep(0.002)
        return super().append(mailbox, flags, date_time, message)


class TestMigrateAccount(unittest.TestCase):
    def setUp(self):
        self.m = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.account = Path(self.tmp.name) / "alice@example.test"
        for folder in ("", ".Archive", ".Sent"):
            base = self.account / folder if folder else self.account
            for sub in ("cur", "new", "tmp"):
                (base / sub).mkdir(parents=True)
        (self.account / "cur" / "1.host:2,S").write_bytes(b"Message-ID: <1@x>\r\n\r\na")
        (self.account / "new" / "2.host").write_bytes(b"Message-ID: <2@x>\r\n\r\nb")
        (self.account / ".Archive" / "cur" / "3.host:2,a").write_bytes(
            b"Message-ID: <3@x>\r\n\r\nc"
        )
        (self.account / ".Archive" / "dovecot-keywords").write_text("0 $Forwarded\n")
        (self.account / ".Sent" / "cur" / "4.host:2,S").write_bytes(
            b"Message-ID: <4@x>\r\n\r\nd"
        )
        os.utime(self.account / "cur" / "1.host:2,S", (1700000000, 1700000000))

    def test_appends_with_flags_folders_and_internal_date(self):
        imap = _FakeImap()
        stats = self.m.AccountStats()
        self.m.migrate_account([imap], self.account, stats)
        self.assertEqual(imap.created, ["Archive", "Sent Items"])
        self.assertEqual(
            [(mailbox, flags) for mailbox, flags, _, _ in imap.appended],
            [
                ("INBOX", "(\\Seen)"),
                ("INBOX", None),
                ("Archive", "($Forwarded)"),
                ("Sent Items", "(\\Seen)"),
            ],
        )
        self.assertEqual(
            imap.appended[0][2], self.m.imaplib.Time2Internaldate(1700000000)
        )
        self.assertEqual((stats.total("found"), stats.total("appended")), (4, 4))

    def test_existing_messages_are_skipped(self):
        imap = _FakeImap(
            existing_headers=[
                b"Message-ID: <1@x>\r\n\r\n",
                b"Message-ID: <3@x>\r\n\r\n",
            ]
        )
        stats = self.m.AccountStats()
        self.m.migrate_account([imap], self.account, stats)
        self.assertEqual(stats.folder("INBOX").appended, 1)
        self.assertEqual(stats.folder("INBOX").skipped, 1)
        self.assertEqual(stats.folder("Archive").skipped, 1)
        self.assertEqual(stats.total("found"), 4)

    def test_parallel_sessions_append_every_message_once(self):
        for index in range(5, 45):
            (self.account / "cur" / f"{index}.host:2,").write_bytes(
                f"Message-ID: <{index}@x>\r\n\r\nbody".encode()
            )
        (self.account / "cur" / "99.host:2,").write_bytes(
            b"Message-ID: <5@x>\r\n\r\nduplicate"
        )
        barrier = threading.Barrier(4)
        imaps = [_SlowImap(barrier=barrier) for _ in range(4)]
        stats = self.m.AccountStats()
        self.m.migrate_account(imaps, self.account, stats)
        appended = [entry for imap in imaps for entry in imap.appended]
        bodies = sorted(message for _, _, _, message in appended)
        self.assertEqual(len(bodies), len(set(bodies)))
        self.assertEqual(stats.total("appended"), 44)
        self.assertEqual(stats.folder("INBOX").skipped, 1)
        self.assertEqual(imaps[0].created, ["Archive", "Sent Items"])
        self.assertTrue(all(not imap.created for imap in imaps[1:]))
        self.assertGreater(sum(1 for imap in imaps if imap.appended), 1)


class TestOpenSessions(unittest.TestCase):
    def setUp(self):
        self.m = _load_module()

    def _args(self, workers):
        return self.m.parse_args(
            [
                "--maildir-root=/x",
                "--imap-host=127.0.0.1",
                "--imap-port=993",
                "--jmap-url=http://127.0.0.1/jmap/",
                "--admin-file=/x/admin.json",
                "--mailbox-map=[]",
                f"--workers={workers}",
                "--done-file=/x/import.done",
            ]
        )

    def test_done_marker_records_the_start_of_the_run(self):
        with tempfile.TemporaryDirectory() as base:
            marker = Path(base) / "import.done"
            self.m.mark_done(marker, 1700000000.4)
            self.assertTrue(marker.is_file())
            self.assertEqual(marker.stat().st_size, len("1700000000\n"))

    def test_opens_one_session_per_worker(self):
        self.m.open_session = lambda args, stalwart, target: "s"
        self.assertEqual(self.m.open_sessions(self._args(3), None, "a@x"), ["s"] * 3)

    def test_refused_extra_session_keeps_the_open_ones(self):
        calls = []

        def open_session(args, stalwart, target):
            calls.append(1)
            if len(calls) > 2:
                raise self.m.imaplib.IMAP4.error("too many connections")
            return "s"

        self.m.open_session = open_session
        self.assertEqual(self.m.open_sessions(self._args(4), None, "a@x"), ["s", "s"])

    def test_refused_first_session_fails(self):
        def open_session(args, stalwart, target):
            raise self.m.imaplib.IMAP4.error("login failed")

        self.m.open_session = open_session
        with self.assertRaises(self.m.imaplib.IMAP4.error):
            self.m.open_sessions(self._args(4), None, "a@x")


class _FakeJmap:
    def __init__(self, scripts, blob_text=""):
        self.scripts = scripts
        self.blob_text = blob_text
        self.calls: list[tuple[str, dict]] = []

    def session(self):
        return {"primaryAccounts": {"urn:ietf:params:jmap:sieve": "acc"}}

    def call(self, using, method, arguments):
        self.calls.append((method, arguments))
        if method == "SieveScript/get":
            return {"list": self.scripts}
        if method == "Blob/get":
            return {"list": [{"data:asText": self.blob_text}]}
        if method == "Blob/upload":
            return {"created": {"b": {"id": "blob1"}}}
        return {}


class TestImportSieve(unittest.TestCase):
    def setUp(self):
        self.m = _load_module()
        self.stalwart = self.m.Stalwart("http://127.0.0.1:1/jmap/", "admin", "secret")
        self.script = self.m.SieveScript("roundcube", "keep;\n")

    def _run(self, jmap):
        original = self.m.Jmap
        self.m.Jmap = lambda url, user, password: jmap
        try:
            return self.stalwart.import_sieve("a@x.org", self.script)
        finally:
            self.m.Jmap = original

    def test_new_script_is_created_and_activated(self):
        jmap = _FakeJmap([])
        self.assertEqual(self._run(jmap), "imported:roundcube (active)")
        method, arguments = jmap.calls[-1]
        self.assertEqual(method, "SieveScript/set")
        self.assertEqual(
            arguments["create"], {"s": {"name": "roundcube", "blobId": "blob1"}}
        )
        self.assertEqual(arguments["onSuccessActivateScript"], "#s")

    def test_identical_script_is_left_alone(self):
        jmap = _FakeJmap(
            [{"id": "s1", "name": "roundcube", "blobId": "b0", "isActive": False}],
            "keep;\n",
        )
        self.assertEqual(self._run(jmap), "unchanged:roundcube")
        self.assertNotIn("SieveScript/set", [method for method, _ in jmap.calls])

    def test_changed_script_is_updated_and_activated(self):
        jmap = _FakeJmap(
            [{"id": "s1", "name": "roundcube", "blobId": "b0", "isActive": False}],
            "old;\n",
        )
        self.assertEqual(self._run(jmap), "updated:roundcube (active)")
        _, arguments = jmap.calls[-1]
        self.assertEqual(arguments["update"], {"s1": {"blobId": "blob1"}})
        self.assertEqual(arguments["onSuccessActivateScript"], "s1")

    def test_impersonation_login_uses_the_master_user_separator(self):
        self.assertEqual(self.stalwart.impersonation_login("a@x.org"), "a@x.org%admin")


class _FakeStalwart:
    def __init__(self):
        self.created: list[tuple[str, str]] = []

    def create_account(self, address, domain_id):
        self.created.append((address, domain_id))


class TestEnsureAccount(unittest.TestCase):
    def setUp(self):
        self.m = _load_module()
        self.stalwart = _FakeStalwart()

    def test_missing_account_is_created_in_its_domain(self):
        self.m.ensure_account(
            self.stalwart, "new@example.org", {"example.org": "d1"}, set(), set()
        )
        self.assertEqual(self.stalwart.created, [("new@example.org", "d1")])

    def test_existing_account_is_kept(self):
        self.m.ensure_account(
            self.stalwart,
            "a@example.org",
            {"example.org": "d1"},
            {"a@example.org"},
            set(),
        )
        self.assertEqual(self.stalwart.created, [])

    def test_alias_address_is_refused(self):
        with self.assertRaises(self.m.MigrationError):
            self.m.ensure_account(
                self.stalwart,
                "a@example.org",
                {"example.org": "d1"},
                set(),
                {"a@example.org"},
            )


if __name__ == "__main__":
    unittest.main()
