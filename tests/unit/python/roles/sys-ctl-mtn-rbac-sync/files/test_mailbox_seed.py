import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from .test_script import LDAP, MAILBOX, load_module


def seed_module():
    """Returns:
    the ``mailbox_seed`` module, loaded the way the RBAC sync script imports it.
    """
    load_module()
    return sys.modules["mailbox_seed"]


class MailboxAdditionsTests(unittest.TestCase):
    def setUp(self):
        self.mod = seed_module()

    def test_an_entry_with_a_primary_address_needs_nothing(self):
        values = {"uid": ["bob"], "mail": ["bob@elsewhere.org"]}

        additions = self.mod.mailbox_additions(
            "uid=bob,ou=users", values, LDAP, MAILBOX
        )

        self.assertEqual(additions, {})

    def test_an_entry_without_mail_gets_its_address_and_the_class(self):
        values = {"uid": ["alice"], "objectclass": ["person"]}

        additions = self.mod.mailbox_additions(
            "uid=alice,ou=users", values, LDAP, MAILBOX
        )

        self.assertEqual(
            additions,
            {"objectClass": ["infinitoMailboxUser"], "mail": ["alice@example.org"]},
        )

    def test_a_class_the_entry_carries_in_any_case_is_not_added_again(self):
        values = {"uid": ["carol"], "objectclass": ["InfinitoMailboxUser"]}

        additions = self.mod.mailbox_additions(
            "uid=carol,ou=users", values, LDAP, MAILBOX
        )

        self.assertEqual(additions, {"mail": ["carol@example.org"]})

    def test_an_entry_without_one_login_is_refused(self):
        values = {"uid": ["david", "davy"]}

        with self.assertRaisesRegex(ValueError, "holds 2 values of uid"):
            self.mod.mailbox_additions("uid=dave,ou=users", values, LDAP, MAILBOX)


class ReadMailboxTests(unittest.TestCase):
    def setUp(self):
        self.mod = seed_module()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name, "mailbox.json")

    def read(self):
        """Returns:
        the result of ``read_mailbox`` on the seed path and what it wrote to stderr.
        """
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = self.mod.read_mailbox(self.path)
        return result, stderr.getvalue()

    def test_the_seed_the_deploy_wrote_is_read(self):
        self.path.write_text(json.dumps(MAILBOX), encoding="utf-8")

        self.assertEqual(self.read(), ((MAILBOX, True), ""))

    def test_a_missing_seed_fails_in_one_line(self):
        (mailbox, readable), stderr = self.read()

        self.assertEqual((mailbox, readable), (None, False))
        self.assertEqual(len(stderr.splitlines()), 1)
        self.assertTrue(stderr.startswith("[mailbox] FAILED FileNotFoundError"))


if __name__ == "__main__":
    unittest.main()
