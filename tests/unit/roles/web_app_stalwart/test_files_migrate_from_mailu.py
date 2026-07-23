import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT


def _load_module():
    path = PROJECT_ROOT / "roles/web-app-stalwart/files/migrate_from_mailu.py"
    spec = importlib.util.spec_from_file_location("migrate_from_mailu", str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # dataclasses resolve their module via sys.modules — register before exec.
    sys.modules["migrate_from_mailu"] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeImap:
    """Minimal IMAP fake capturing the calls migrate_account issues."""

    def __init__(self, existing_headers: list[bytes] | None = None):
        self.created: list[str] = []
        self.selected: list[str] = []
        self.appended: list[tuple[str, str | None, bytes]] = []
        self._existing_headers = existing_headers or []

    def create(self, mailbox):
        self.created.append(mailbox)
        return "OK", [b""]

    def select(self, mailbox, readonly=False):
        self.selected.append(mailbox)
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
        self.appended.append((mailbox, flags, message))
        return "OK", [b""]


class TestFlagAndFolderMapping(unittest.TestCase):
    def setUp(self):
        self.m = _load_module()

    def test_maildir_flags_to_imap(self):
        self.assertEqual(self.m.maildir_flags_to_imap("123.M1.host:2,S"), "(\\Seen)")
        self.assertEqual(
            self.m.maildir_flags_to_imap("123.M1.host:2,FS"),
            "(\\Flagged \\Seen)",
        )
        self.assertEqual(self.m.maildir_flags_to_imap("123.M1.host:2,"), "")
        self.assertEqual(self.m.maildir_flags_to_imap("123.M1.host"), "")
        # Unknown info letters are ignored, known ones kept.
        self.assertEqual(self.m.maildir_flags_to_imap("a:2,XR"), "(\\Answered)")

    def test_maildir_folder_to_imap(self):
        self.assertEqual(self.m.maildir_folder_to_imap("", "/"), "INBOX")
        self.assertEqual(self.m.maildir_folder_to_imap(".Archive", "/"), "Archive")
        self.assertEqual(
            self.m.maildir_folder_to_imap(".Archive.2024", "/"), "Archive/2024"
        )
        self.assertEqual(
            self.m.maildir_folder_to_imap(".Archive.2024", "."), "Archive.2024"
        )

    def test_extract_message_id(self):
        raw = b"Message-ID: <x@y>\r\nSubject: s\r\n\r\nbody"
        self.assertEqual(self.m.extract_message_id(raw), "<x@y>")
        self.assertEqual(self.m.extract_message_id(b"Subject: s\r\n\r\n"), "")


class TestMaildirWalk(unittest.TestCase):
    def setUp(self):
        self.m = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.account = Path(self.tmp.name) / "alice@example.test"
        for folder in ("", ".Archive"):
            base = self.account / folder if folder else self.account
            for sub in ("cur", "new", "tmp"):
                (base / sub).mkdir(parents=True)
        (self.account / "cur" / "1.host:2,S").write_bytes(b"Message-ID: <1@x>\r\n\r\na")
        (self.account / "new" / "2.host").write_bytes(b"Message-ID: <2@x>\r\n\r\nb")
        (self.account / ".Archive" / "cur" / "3.host:2,").write_bytes(
            b"Message-ID: <3@x>\r\n\r\nc"
        )
        # Non-maildir noise must be ignored.
        (self.account / ".dovecot.sieve.d").mkdir()

    def test_iter_maildir_folders_and_messages(self):
        folders = self.m.iter_maildir_folders(self.account)
        self.assertEqual([name for name, _ in folders], ["", ".Archive"])
        root_msgs = self.m.iter_messages(self.account)
        self.assertEqual([p.name for p in root_msgs], ["1.host:2,S", "2.host"])

    def test_migrate_account_appends_and_dedups(self):
        imap = _FakeImap()
        stats = self.m.AccountStats()
        self.m.migrate_account(imap, self.account, "/", stats)
        self.assertEqual(stats.folder("INBOX").appended, 2)
        self.assertEqual(stats.folder("Archive").appended, 1)
        self.assertEqual(imap.created, ["Archive"])
        self.assertEqual(
            [(mailbox, flags) for mailbox, flags, _ in imap.appended],
            [("INBOX", "(\\Seen)"), ("INBOX", None), ("Archive", None)],
        )

    def test_migrate_account_skips_existing_message_ids(self):
        imap = _FakeImap(
            existing_headers=[
                b"Message-ID: <1@x>\r\n\r\n",
                b"Message-ID: <3@x>\r\n\r\n",
            ]
        )
        stats = self.m.AccountStats()
        self.m.migrate_account(imap, self.account, "/", stats)
        self.assertEqual(stats.folder("INBOX").appended, 1)  # only <2@x>
        self.assertEqual(stats.folder("INBOX").skipped, 1)
        self.assertEqual(stats.folder("Archive").skipped, 1)
        self.assertEqual(stats.folder("Archive").appended, 0)


class TestExistingMessageIds(unittest.TestCase):
    def setUp(self):
        self.m = _load_module()

    def test_collects_ids_from_fetch(self):
        imap = _FakeImap(
            existing_headers=[
                b"Message-ID: <a@x>\r\n\r\n",
                b"Message-ID: <b@x>\r\n\r\n",
            ]
        )
        imap.select("INBOX")
        self.assertEqual(self.m.existing_message_ids(imap), {"<a@x>", "<b@x>"})

    def test_empty_folder(self):
        imap = _FakeImap()
        imap.select("INBOX")
        self.assertEqual(self.m.existing_message_ids(imap), set())


if __name__ == "__main__":
    unittest.main()
