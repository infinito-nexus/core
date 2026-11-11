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

MODULE_PATH = PROJECT_ROOT / "library" / "ldap_entries.py"


class _NoSuchObjectError(Exception):
    pass


def _fake_ldap() -> types.ModuleType:
    fake = types.ModuleType("ldap")
    fake.SCOPE_BASE = 0
    fake.MOD_ADD, fake.MOD_DELETE, fake.MOD_REPLACE = 0, 1, 2
    fake.OPT_REFERRALS = 8
    fake.LDAPError = Exception
    fake.NO_SUCH_OBJECT = _NoSuchObjectError
    modlist = types.ModuleType("ldap.modlist")
    modlist.addModlist = lambda attributes: sorted(attributes.items())
    fake.modlist = modlist
    ldap_filter = types.ModuleType("ldap.filter")
    ldap_filter.escape_filter_chars = lambda value: value.replace("*", "\\2a")
    fake.filter = ldap_filter
    return fake


def _load_ldap_entries() -> ModuleType:
    fake = _fake_ldap()
    sys.modules["ldap"] = fake
    sys.modules["ldap.modlist"] = fake.modlist
    sys.modules["ldap.filter"] = fake.filter
    spec = importlib.util.spec_from_file_location(
        "library_ldap_entries", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load: {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_MOD = _load_ldap_entries()
DN = "uid=alice,ou=users,dc=example,dc=org"


class _Directory:
    def __init__(self, entries):
        self.entries = entries
        self.added = []
        self.modified = []

    def search_s(self, dn, scope, filterstr="(objectClass=*)", attrlist=None):
        if dn not in self.entries:
            raise _NoSuchObjectError(dn)
        entry = self.entries[dn]
        if filterstr != "(objectClass=*)":
            name, value = filterstr[1:-1].split("=", 1)
            values = entry.get(name, [])
            return (
                [(dn, entry)]
                if value.lower() in {v.decode().lower() for v in values}
                else []
            )
        wanted = {a.lower() for a in attrlist or []}
        return [(dn, {k: v for k, v in entry.items() if k.lower() in wanted})]

    def add_s(self, dn, modlist):
        self.added.append((dn, modlist))

    def modify_s(self, dn, changes):
        self.modified.append((dn, changes))


class CreateTests(unittest.TestCase):
    def test_missing_entry_is_added_with_every_attribute(self):
        directory = _Directory({})
        changed = _MOD.apply(
            directory,
            "create",
            DN,
            {"objectClass": ["person"], "uidNumber": 1001},
            False,
        )
        self.assertTrue(changed)
        self.assertEqual(
            directory.added,
            [(DN, [("objectClass", [b"person"]), ("uidNumber", [b"1001"])])],
        )

    def test_existing_entry_is_left_alone(self):
        directory = _Directory({DN: {"objectClass": [b"person"]}})
        self.assertFalse(_MOD.apply(directory, "create", DN, {"cn": "Other"}, False))
        self.assertEqual(directory.added, [])


class PresentTests(unittest.TestCase):
    def test_only_missing_values_are_added(self):
        directory = _Directory({DN: {"objectClass": [b"person", b"nextcloudUser"]}})
        changed = _MOD.apply(
            directory,
            "present",
            DN,
            {"objectClass": ["NextcloudUser", "ldapPublicKey"]},
            False,
        )
        self.assertTrue(changed)
        self.assertEqual(
            directory.modified, [(DN, [(0, "objectClass", [b"ldapPublicKey"])])]
        )

    def test_absent_attribute_counts_as_missing(self):
        directory = _Directory({DN: {"objectClass": [b"person"]}})
        _MOD.apply(directory, "present", DN, {"mail": "alice@example.org"}, False)
        self.assertEqual(
            directory.modified, [(DN, [(0, "mail", [b"alice@example.org"])])]
        )

    def test_nothing_missing_changes_nothing(self):
        directory = _Directory({DN: {"mail": [b"alice@example.org"]}})
        self.assertFalse(
            _MOD.apply(directory, "present", DN, {"mail": "alice@example.org"}, False)
        )
        self.assertEqual(directory.modified, [])


class ExactTests(unittest.TestCase):
    def test_differing_values_are_replaced(self):
        directory = _Directory({DN: {"objectClass": [b"person", b"nextcloudUser"]}})
        _MOD.apply(directory, "exact", DN, {"objectClass": ["person"]}, False)
        self.assertEqual(directory.modified, [(DN, [(2, "objectClass", [b"person"])])])

    def test_absent_attribute_is_added(self):
        directory = _Directory({DN: {"objectClass": [b"person"]}})
        _MOD.apply(directory, "exact", DN, {"mail": "alice@example.org"}, False)
        self.assertEqual(
            directory.modified, [(DN, [(0, "mail", [b"alice@example.org"])])]
        )

    def test_equal_values_change_nothing(self):
        directory = _Directory({DN: {"mail": [b"alice@example.org"]}})
        self.assertFalse(
            _MOD.apply(directory, "exact", DN, {"mail": "alice@example.org"}, False)
        )


class CheckModeTests(unittest.TestCase):
    def test_reports_change_without_writing(self):
        directory = _Directory({})
        self.assertTrue(_MOD.apply(directory, "create", DN, {"cn": "Alice"}, True))
        self.assertEqual(directory.added, [])
        directory = _Directory({DN: {"objectClass": [b"person"]}})
        self.assertTrue(_MOD.apply(directory, "present", DN, {"mail": "a@x"}, True))
        self.assertEqual(directory.modified, [])


if __name__ == "__main__":
    unittest.main()
