from __future__ import annotations

import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from plugins.lookup import users_non_reserved

USERS = {
    "admin": {"accounts": ["identity", "mailbox"]},
    "helpdesk": {"accounts": ["mailbox"]},
    "bounce": {"accounts": ["identity"]},
    "broken": "not-a-dict",
}


class TestUsersNonReservedLookup(unittest.TestCase):
    def setUp(self) -> None:
        self.lookup = users_non_reserved.LookupModule()
        self.lookup._templar = None

    def _run(self, users):
        inner = mock.Mock()
        inner.run.return_value = [users]
        with mock.patch.object(
            users_non_reserved.lookup_loader, "get", return_value=inner
        ):
            return self.lookup.run([], variables={})[0]

    def test_keeps_only_identity_provisioned_users(self):
        self.assertEqual(sorted(self._run(USERS)), ["admin", "bounce"])

    def test_mailbox_only_users_are_excluded(self):
        self.assertNotIn("helpdesk", self._run(USERS))

    def test_empty_input(self):
        self.assertEqual(self._run({}), {})

    def test_terms_raise(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["x"], variables={})


if __name__ == "__main__":
    unittest.main()
