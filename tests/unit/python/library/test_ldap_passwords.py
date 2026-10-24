from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from typing import TYPE_CHECKING

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from types import ModuleType

sys.path.insert(0, str(PROJECT_ROOT))

MODULE_PATH = PROJECT_ROOT / "library" / "ldap_passwords.py"
URI = "ldap://ldap:389"
ALICE = "uid=alice,ou=users,dc=example,dc=org"
BOB = "uid=bob,ou=users,dc=example,dc=org"


class _LDAPError(Exception):
    pass


class _InvalidCredentialsError(_LDAPError):
    pass


class _Server:
    def __init__(self, passwords, unreachable=(), refuse_change=()):
        self.passwords = dict(passwords)
        self.unreachable = set(unreachable)
        self.refuse_change = set(refuse_change)
        self.changes = []
        self.unbinds = 0

    def initialize(self, uri):
        if uri != URI:
            raise _LDAPError(f"unexpected uri {uri}")
        return _Connection(self)


class _Connection:
    def __init__(self, server):
        self.server = server

    def simple_bind_s(self, dn, passwd):
        if dn in self.server.unreachable:
            raise _LDAPError("server down")
        if self.server.passwords.get(dn) != passwd:
            raise _InvalidCredentialsError(dn)

    def unbind(self):
        self.server.unbinds += 1

    def passwd_s(self, dn, oldpw, newpw):
        if dn in self.server.refuse_change:
            raise _LDAPError("insufficient access")
        self.server.changes.append((dn, oldpw, newpw))
        self.server.passwords[dn] = newpw


def _load(server) -> ModuleType:
    fake = types.ModuleType("ldap")
    fake.LDAPError = _LDAPError
    fake.INVALID_CREDENTIALS = _InvalidCredentialsError
    fake.OPT_REFERRALS = 8
    fake.initialize = server.initialize
    sys.modules["ldap"] = fake
    spec = importlib.util.spec_from_file_location(
        "library_ldap_passwords", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load: {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def _converge(server, entries, check_mode=False):
    mod = _load(server)
    admin = server.initialize(URI)
    return mod.converge(admin, URI, entries, check_mode)


class ConvergeTests(unittest.TestCase):
    def test_a_password_that_already_binds_is_left_alone(self):
        server = _Server({ALICE: "current"})
        changed, errors = _converge(server, [{"dn": ALICE, "passwd": "current"}])
        self.assertEqual((changed, errors), ([], {}))
        self.assertEqual(server.changes, [])

    def test_a_password_that_does_not_bind_is_set(self):
        server = _Server({ALICE: "stale", BOB: "current"})
        changed, errors = _converge(
            server,
            [{"dn": ALICE, "passwd": "fresh"}, {"dn": BOB, "passwd": "current"}],
        )
        self.assertEqual((changed, errors), ([ALICE], {}))
        self.assertEqual(server.changes, [(ALICE, None, "fresh")])

    def test_an_entry_without_a_password_yet_is_set(self):
        server = _Server({})
        changed, _ = _converge(server, [{"dn": ALICE, "passwd": "fresh"}])
        self.assertEqual(changed, [ALICE])

    def test_every_probe_connection_is_unbound(self):
        server = _Server({ALICE: "stale", BOB: "current"})
        _converge(
            server,
            [{"dn": ALICE, "passwd": "fresh"}, {"dn": BOB, "passwd": "current"}],
        )
        self.assertEqual(server.unbinds, 2)

    def test_check_mode_reports_without_writing(self):
        server = _Server({ALICE: "stale"})
        changed, errors = _converge(
            server, [{"dn": ALICE, "passwd": "fresh"}], check_mode=True
        )
        self.assertEqual((changed, errors), ([ALICE], {}))
        self.assertEqual(server.changes, [])


class FailureTests(unittest.TestCase):
    def test_a_bind_error_names_the_entry_and_the_rest_still_converge(self):
        server = _Server({BOB: "stale"}, unreachable={ALICE})
        changed, errors = _converge(
            server,
            [{"dn": ALICE, "passwd": "fresh"}, {"dn": BOB, "passwd": "fresh"}],
        )
        self.assertEqual(changed, [BOB])
        self.assertEqual(list(errors), [ALICE])
        self.assertIn(ALICE, errors[ALICE])

    def test_a_refused_change_names_the_entry_and_is_not_reported_changed(self):
        server = _Server({ALICE: "stale"}, refuse_change={ALICE})
        changed, errors = _converge(server, [{"dn": ALICE, "passwd": "fresh"}])
        self.assertEqual(changed, [])
        self.assertIn("Unable to set the password of " + ALICE, errors[ALICE])


if __name__ == "__main__":
    unittest.main()
