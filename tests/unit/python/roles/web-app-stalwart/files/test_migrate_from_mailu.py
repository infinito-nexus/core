import importlib.util
import os
import sys
import tempfile
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


class TestServerLayout(unittest.TestCase):
    def setUp(self):
        self.m = _load_module()
        self.layout = self.m.server_layout(_FakeImap())

    def test_reads_separator_and_special_use(self):
        self.assertEqual(self.layout.separator, "/")
        self.assertEqual(
            self.layout.special_use, {"\\Sent": "Sent Items", "\\Junk": "Junk Mail"}
        )

    def test_nested_folder_uses_the_server_separator(self):
        self.assertEqual(
            self.m.destination_mailbox(".Archive.2024", self.layout), "Archive/2024"
        )

    def test_special_folder_lands_in_the_special_use_folder(self):
        self.assertEqual(self.m.destination_mailbox(".Sent", self.layout), "Sent Items")
        self.assertEqual(self.m.destination_mailbox(".Spam", self.layout), "Junk Mail")

    def test_special_name_without_server_counterpart_keeps_its_name(self):
        self.assertEqual(self.m.destination_mailbox(".Drafts", self.layout), "Drafts")

    def test_ambiguous_separator_fails(self):
        imap = _FakeImap(list_lines=[b'(\\X) "/" A', b'(\\X) "." B'])
        with self.assertRaises(self.m.MigrationError):
            self.m.server_layout(imap)

    def test_imap_quote_escapes(self):
        self.assertEqual(self.m.imap_quote('My "x"\\y'), '"My \\"x\\"\\\\y"')


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
        self.m.migrate_account(imap, self.account, stats)
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
        self.m.migrate_account(imap, self.account, stats)
        self.assertEqual(stats.folder("INBOX").appended, 1)
        self.assertEqual(stats.folder("INBOX").skipped, 1)
        self.assertEqual(stats.folder("Archive").skipped, 1)
        self.assertEqual(stats.total("found"), 4)

    def test_existing_keys_collects_the_server_side_keys(self):
        imap = _FakeImap(
            existing_headers=[b"Message-ID: <a@x>\r\n\r\n", b"X: 1\r\n\r\n"]
        )
        self.assertEqual(self.m.existing_keys(imap), {"<a@x>"})


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
