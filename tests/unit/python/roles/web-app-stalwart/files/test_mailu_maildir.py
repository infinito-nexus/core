import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT


def _load_module():
    path = PROJECT_ROOT / "roles/web-app-stalwart/files/python/mailu_maildir.py"
    spec = importlib.util.spec_from_file_location("mailu_maildir", str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["mailu_maildir"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestFlagMapping(unittest.TestCase):
    def setUp(self):
        self.m = _load_module()

    def test_system_flags(self):
        self.assertEqual(
            self.m.maildir_flags_to_imap("1.host:2,FS", {}), "(\\Flagged \\Seen)"
        )

    def test_no_info_means_no_flags(self):
        self.assertEqual(self.m.maildir_flags_to_imap("1.host", {}), "")
        self.assertEqual(self.m.maildir_flags_to_imap("1.host:2,", {}), "")

    def test_keyword_letters_map_to_their_names(self):
        self.assertEqual(
            self.m.maildir_flags_to_imap("1.host:2,Sab", {"a": "$Forwarded"}),
            "(\\Seen $Forwarded)",
        )

    def test_read_keywords(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "dovecot-keywords").write_text(
                "0 $Forwarded\n1 Work\n30 Ignored\n"
            )
            self.assertEqual(
                self.m.read_keywords(Path(tmp)), {"a": "$Forwarded", "b": "Work"}
            )

    def test_folder_names(self):
        self.assertEqual(self.m.maildir_folder_to_imap("", "/"), "INBOX")
        self.assertEqual(
            self.m.maildir_folder_to_imap(".Archive.2024", "/"), "Archive/2024"
        )


class TestDedupKey(unittest.TestCase):
    def setUp(self):
        self.m = _load_module()

    def test_message_id_wins(self):
        self.assertEqual(
            self.m.dedup_key(b"Message-ID: <x@y>\r\nSubject: s\r\n\r\nb"), "<x@y>"
        )

    def test_fallback_digest_ignores_line_endings_and_folding(self):
        lf = b"Date: Mon, 1 Jan 2024\nFrom: a@b.c\nSubject: long\n subject\n\nbody"
        crlf = b"Date: Mon, 1 Jan 2024\r\nFrom: a@b.c\r\nSubject: long subject\r\n\r\n"
        self.assertTrue(self.m.dedup_key(lf).startswith("sha256:"))
        self.assertEqual(self.m.dedup_key(lf), self.m.dedup_key(crlf))

    def test_no_identifying_header_gives_empty_key(self):
        self.assertEqual(self.m.dedup_key(b"X-Other: 1\r\n\r\nbody"), "")


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
        (self.account / "cur" / "1.host:2,S").write_bytes(b"a")
        (self.account / "new" / "2.host").write_bytes(b"b")
        (self.account / ".sieve.d").mkdir()

    def test_folders_and_messages(self):
        self.assertEqual(
            [name for name, _ in self.m.iter_maildir_folders(self.account)],
            ["", ".Archive"],
        )
        self.assertEqual(
            [p.name for p in self.m.iter_messages(self.account)],
            ["1.host:2,S", "2.host"],
        )


class TestSieve(unittest.TestCase):
    def setUp(self):
        self.m = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mailbox = Path(self.tmp.name)
        (self.mailbox / "sieve").mkdir()

    def test_symlinked_active_script(self):
        (self.mailbox / "sieve" / "roundcube.sieve").write_text('require "fileinto";\n')
        (self.mailbox / ".dovecot.sieve").symlink_to("sieve/roundcube.sieve")
        script = self.m.read_active_sieve(self.mailbox)
        self.assertEqual(
            (script.name, script.content), ("roundcube", 'require "fileinto";\n')
        )

    def test_absolute_link_from_the_mailu_container_resolves_by_name(self):
        (self.mailbox / "sieve" / "x.sieve").write_text("keep;\n")
        (self.mailbox / ".dovecot.sieve").symlink_to(
            "/mail/alice@example.test/sieve/x.sieve"
        )
        self.assertEqual(self.m.read_active_sieve(self.mailbox).name, "x")

    def test_plain_file_is_named_dovecot(self):
        (self.mailbox / ".dovecot.sieve").write_text("keep;\n")
        self.assertEqual(self.m.read_active_sieve(self.mailbox).name, "dovecot")

    def test_empty_or_missing_script_is_none(self):
        self.assertIsNone(self.m.read_active_sieve(self.mailbox))
        (self.mailbox / ".dovecot.sieve").write_text("  \n")
        self.assertIsNone(self.m.read_active_sieve(self.mailbox))

    def test_script_names(self):
        self.assertEqual(
            self.m.sieve_script_name("a@x.org", "a@x.org", "roundcube"), "roundcube"
        )
        self.assertEqual(
            self.m.sieve_script_name("old@x.org", "a@x.org", "roundcube"),
            "old-roundcube",
        )
        self.assertEqual(
            self.m.sieve_script_name("a@x.org", "a@x.org", "Vacation"), "mailu-Vacation"
        )


class TestPlanning(unittest.TestCase):
    def setUp(self):
        self.m = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for name in (
            "Alice@example.org",
            "kb@example.org",
            "v@example.net",
            "lost+found",
            "notes",
        ):
            (root / name).mkdir()
        (root / "file@example.org").write_text("")
        self.mailboxes = self.m.discover_mailboxes(root)

    def test_discovers_every_address_directory(self):
        self.assertEqual(
            [m.address for m in self.mailboxes],
            ["alice@example.org", "kb@example.org", "v@example.net"],
        )

    def test_unserved_domain_is_skipped_by_address(self):
        plan = self.m.plan_imports(self.mailboxes, {}, {"example.org"})
        self.assertEqual(
            plan.skipped,
            [("v@example.net", "domain example.net is not served by Stalwart")],
        )
        self.assertEqual(sorted(plan.targets), ["alice@example.org", "kb@example.org"])

    def test_mapped_mailbox_merges_after_the_target_own_mailbox(self):
        plan = self.m.plan_imports(
            self.mailboxes, {"alice@example.org": "kb@example.org"}, {"example.org"}
        )
        self.assertEqual(list(plan.targets), ["kb@example.org"])
        self.assertEqual(
            [m.address for m in plan.targets["kb@example.org"]],
            ["kb@example.org", "alice@example.org"],
        )

    def test_mapping_into_an_unserved_domain_fails(self):
        with self.assertRaises(ValueError):
            self.m.plan_imports(
                self.mailboxes, {"alice@example.org": "k@example.net"}, {"example.org"}
            )

    def test_unknown_mapping_source_is_reported(self):
        plan = self.m.plan_imports(
            self.mailboxes, {"gone@example.org": "kb@example.org"}, {"example.org"}
        )
        self.assertEqual(plan.missing_sources, ["gone@example.org"])


class TestMailboxMap(unittest.TestCase):
    def setUp(self):
        self.m = _load_module()

    def test_parses_and_lowercases(self):
        raw = json.dumps([{"source": "Alice@example.org", "target": "KB@example.org"}])
        self.assertEqual(
            self.m.parse_mailbox_map(raw), {"alice@example.org": "kb@example.org"}
        )

    def test_rejects_repeated_source(self):
        raw = json.dumps([{"source": "a@x.org", "target": "b@x.org"}] * 2)
        with self.assertRaises(ValueError):
            self.m.parse_mailbox_map(raw)

    def test_rejects_chains(self):
        raw = json.dumps(
            [
                {"source": "a@x.org", "target": "b@x.org"},
                {"source": "b@x.org", "target": "c@x.org"},
            ]
        )
        with self.assertRaises(ValueError):
            self.m.parse_mailbox_map(raw)

    def test_rejects_self_mapping(self):
        with self.assertRaises(ValueError):
            self.m.parse_mailbox_map(
                json.dumps([{"source": "a@x.org", "target": "a@x.org"}])
            )


if __name__ == "__main__":
    unittest.main()
