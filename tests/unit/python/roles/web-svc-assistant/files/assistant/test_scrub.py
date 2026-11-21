from __future__ import annotations

import unittest

from . import load

scrub = load("scrub")

KEY_KIND = "OPENSSH PRIVATE"
PRIVATE_KEY = f"-----BEGIN {KEY_KIND} KEY-----\nAAAAB3Nza\n-----END {KEY_KIND} KEY-----"
VAULT = f"$ANSIBLE_{'VAULT'};1.1;AES256\n  6638643965\n  3533316462"


class TestIndexable(unittest.TestCase):
    def test_a_markdown_document_is_read(self) -> None:
        self.assertTrue(scrub.indexable("administration/backup.md"))

    def test_other_file_kinds_are_skipped(self) -> None:
        self.assertFalse(scrub.indexable("administration/backup.yml"))

    def test_inventory_and_variable_paths_are_skipped(self) -> None:
        for path in (
            "inventories/host/README.md",
            "host_vars/x.md",
            "group_vars/all/notes.md",
        ):
            with self.subTest(path=path):
                self.assertFalse(scrub.indexable(path))

    def test_a_secret_file_name_is_skipped(self) -> None:
        self.assertFalse(scrub.indexable("notes/.env"))


class TestScrub(unittest.TestCase):
    def test_a_private_key_is_masked(self) -> None:
        self.assertNotIn("AAAAB3Nza", scrub.scrub(f"before\n{PRIVATE_KEY}\nafter"))

    def test_a_vault_block_is_masked(self) -> None:
        self.assertNotIn(
            "6638643965", scrub.scrub(f"secret: !vault |\n  {VAULT}\nnext")
        )

    def test_an_email_address_is_masked(self) -> None:
        self.assertEqual(
            scrub.scrub("write to anna.biber@example.org today"),
            f"write to {scrub.MASK} today",
        )

    def test_credentials_in_a_url_are_masked(self) -> None:
        self.assertNotIn(
            "hunter22", scrub.scrub("clone https://biber:hunter22@git.example/repo")
        )

    def test_plain_prose_is_kept(self) -> None:
        prose = "# Backup\n\nThe nightly backup runs at 03:00 and keeps seven days."
        self.assertEqual(scrub.scrub(prose), prose)

    def test_masking_twice_changes_nothing(self) -> None:
        once = scrub.scrub(f"password: correcthorse\n{PRIVATE_KEY}\nmail a@b.example")
        self.assertEqual(scrub.scrub(once), once)
        self.assertFalse(scrub.leaks(once))

    def test_an_unmasked_secret_is_reported(self) -> None:
        self.assertTrue(scrub.leaks("api_key: abcdef123456"))


if __name__ == "__main__":
    unittest.main()
