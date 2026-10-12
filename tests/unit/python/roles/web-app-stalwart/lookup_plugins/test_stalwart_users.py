from __future__ import annotations

import importlib.util
import sys
import unittest
from typing import ClassVar
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


MODULE = _load_module(
    "roles/web-app-stalwart/lookup_plugins/stalwart_users.py", "stalwart_users"
)


class TestStalwartUsers(unittest.TestCase):
    CATALOGUE: ClassVar[dict] = {
        "administrator": {
            "username": "administrator",
            "accounts": ["host", "mailbox", "identity"],
        },
        "contact": {"username": "contact", "accounts": ["mailbox"]},
        "helpdesk": {
            "username": "helpdesk",
            "accounts": ["mailbox"],
            "roles": ["bot"],
        },
        "relay": {"username": "relay", "accounts": [], "roles": ["bot"]},
        "stalwartadmin": {"username": "stalwartadmin", "accounts": []},
        "root": {"username": "root", "accounts": ["host"]},
        "arduino": {"username": "arduino"},
        "broken": "not-a-mapping",
    }

    def setUp(self):
        self.lookup = MODULE.LookupModule()
        self.catalogue = dict(self.CATALOGUE)

        def _get(name, *args, **kwargs):
            plugin = MagicMock()
            plugin.run.side_effect = lambda terms, variables=None, **kw: [
                self.catalogue
            ]
            return plugin

        patcher = patch.object(MODULE.lookup_loader, "get", side_effect=_get)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self):
        return self.lookup.run(None, variables={})[0]

    def test_selects_mailbox_holders_and_bots_only(self):
        self.assertEqual(
            sorted(self._run()),
            ["administrator", "contact", "helpdesk", "relay"],
        )

    def test_a_bot_without_a_mailbox_survives_the_filter(self):
        """04_manage_user.yml gates the submission credential on the role, so
        dropping it would stop persisting that bot a secret."""
        self.assertIn("relay", self._run())

    def test_the_recovery_admin_gets_no_jmap_account(self):
        """meta/users.yml declares stalwartadmin with accounts: [] -- it is the
        STALWART_RECOVERY_ADMIN credential, not a principal in the directory."""
        self.assertNotIn("stalwartadmin", self._run())

    def test_users_no_stalwart_task_acts_on_are_dropped(self):
        selected = self._run()
        self.assertNotIn("root", selected)
        self.assertNotIn("arduino", selected)

    def test_entries_keep_the_shape_lookup_users_yields(self):
        self.assertEqual(self._run()["contact"], self.CATALOGUE["contact"])

    def test_a_non_list_accounts_declaration_is_loud(self):
        self.catalogue = {"bent": {"username": "bent", "accounts": "mailbox"}}
        with self.assertRaises(AnsibleError) as ctx:
            self._run()
        self.assertIn("bent", str(ctx.exception))

    def test_positional_terms_are_rejected(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["mailbox"], variables={})


if __name__ == "__main__":
    unittest.main()
