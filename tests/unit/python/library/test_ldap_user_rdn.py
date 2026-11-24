from __future__ import annotations

import importlib.util
import sys
import types
import unittest
import unittest.mock

from . import PROJECT_ROOT

MODULE_PATH = PROJECT_ROOT / "library" / "ldap_user_rdn.py"


class _LdapError(Exception):
    pass


class _TypeOrValueExistsError(_LdapError):
    pass


class _NoSuchAttributeError(_LdapError):
    pass


def _fake_ldap() -> types.ModuleType:
    fake = types.ModuleType("ldap")
    fake.MOD_ADD, fake.MOD_DELETE = 0, 1
    fake.OPT_REFERRALS = 8
    fake.LDAPError = _LdapError
    fake.TYPE_OR_VALUE_EXISTS = _TypeOrValueExistsError
    fake.NO_SUCH_ATTRIBUTE = _NoSuchAttributeError
    return fake


def _load_ldap_user_rdn() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "library_ldap_user_rdn", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load: {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    with unittest.mock.patch.dict(sys.modules, {"ldap": _fake_ldap()}):
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_MOD = _load_ldap_user_rdn()

OLD_DN = "uid=platform_administrator,ou=users,dc=x"
NEW_DN = "uid=platformadmin,ou=users,dc=x"
BIBER_DN = "uid=biber,ou=users,dc=x"
ADMIN_GROUP = "cn=app-administrator,ou=roles,dc=x"
POSIX_GROUP = "cn=app-posix,ou=roles,dc=x"
OTHER_GROUP = "cn=app-editor,ou=roles,dc=x"
MEMBER = {"dn": ADMIN_GROUP, "attribute": "member", "old": OLD_DN, "new": NEW_DN}
MEMBER_UID = {
    "dn": POSIX_GROUP,
    "attribute": "memberUid",
    "old": "platform_administrator",
    "new": "platformadmin",
}


def _rename(move, references):
    return {
        "dn": OLD_DN,
        "new_rdn": "uid=platformadmin",
        "move": move,
        "references": references,
    }


def _result():
    return {"renamed_dns": [], "rewritten": []}


class _Directory:
    def __init__(self, entries):
        self.entries = {
            dn: {name: list(values) for name, values in attributes.items()}
            for dn, attributes in entries.items()
        }
        self.writes = []

    def rename_s(self, dn, newrdn, delold):
        self.writes.append(("rename", dn, newrdn, delold))
        attributes = self.entries.pop(dn)
        rdn, parent = dn.split(",", 1)
        old_name, old_value = rdn.split("=", 1)
        new_name, new_value = newrdn.split("=", 1)
        if delold:
            attributes[old_name].remove(old_value.encode())
        if new_value.encode() not in attributes.setdefault(new_name, []):
            attributes[new_name].append(new_value.encode())
        self.entries[f"{newrdn},{parent}"] = attributes

    def modify_s(self, dn, changes):
        self.writes.append(("modify", dn, changes))
        attributes = self.entries[dn]
        for operation, name, values in changes:
            current = attributes.setdefault(name, [])
            for value in values:
                if operation == 0:
                    if value in current:
                        raise _TypeOrValueExistsError(name)
                    current.append(value)
                else:
                    if value not in current:
                        raise _NoSuchAttributeError(name)
                    current.remove(value)
            if name == "member" and not current:
                raise _LdapError("object class violation: groupOfNames needs a member")


class _RefintDirectory(_Directory):
    def rename_s(self, dn, newrdn, delold):
        super().rename_s(dn, newrdn, delold)
        new_dn = f"{newrdn},{dn.split(',', 1)[1]}"
        for attributes in self.entries.values():
            members = attributes.get("member", [])
            if dn.encode() in members:
                members[members.index(dn.encode())] = new_dn.encode()


def _directory(cls, moved):
    entries = {
        BIBER_DN: {"uid": [b"biber"]},
        ADMIN_GROUP: {"member": [BIBER_DN.encode(), OLD_DN.encode()]},
        POSIX_GROUP: {"memberUid": [b"biber", b"platform_administrator"]},
        OTHER_GROUP: {"member": [BIBER_DN.encode()]},
    }
    if moved:
        entries[NEW_DN] = {"uid": [b"platformadmin"]}
    else:
        entries[OLD_DN] = {"uid": [b"platformadmin", b"platform_administrator"]}
    return cls(entries)


class MoveTests(unittest.TestCase):
    def test_the_entry_moves_and_keeps_one_uid(self):
        directory = _directory(_Directory, False)
        _MOD.migrate(directory, [_rename(True, [])], False, _result())
        self.assertNotIn(OLD_DN, directory.entries)
        self.assertEqual(directory.entries[NEW_DN]["uid"], [b"platformadmin"])
        self.assertIn(("rename", OLD_DN, "uid=platformadmin", 1), directory.writes)

    def test_every_listed_group_value_follows_the_entry(self):
        directory = _directory(_Directory, False)
        result = _result()
        _MOD.migrate(
            directory, [_rename(True, [MEMBER, MEMBER_UID])], False, result
        )
        self.assertEqual(
            directory.entries[ADMIN_GROUP]["member"],
            [BIBER_DN.encode(), NEW_DN.encode()],
        )
        self.assertEqual(
            directory.entries[POSIX_GROUP]["memberUid"], [b"biber", b"platformadmin"]
        )
        self.assertEqual(result["renamed_dns"], [OLD_DN])
        self.assertEqual(
            result["rewritten"],
            [
                {"dn": ADMIN_GROUP, "attribute": "member"},
                {"dn": POSIX_GROUP, "attribute": "memberUid"},
            ],
        )

    def test_a_group_not_listed_is_left_alone(self):
        directory = _directory(_Directory, False)
        _MOD.migrate(directory, [_rename(True, [MEMBER, MEMBER_UID])], False, _result())
        self.assertEqual(directory.entries[OTHER_GROUP]["member"], [BIBER_DN.encode()])
        self.assertFalse([write for write in directory.writes if write[1] == OTHER_GROUP])

    def test_a_group_naming_only_the_entry_never_runs_empty(self):
        directory = _Directory(
            {
                OLD_DN: {"uid": [b"platformadmin", b"platform_administrator"]},
                ADMIN_GROUP: {"member": [OLD_DN.encode()]},
            }
        )
        _MOD.migrate(directory, [_rename(True, [MEMBER])], False, _result())
        self.assertEqual(directory.entries[ADMIN_GROUP]["member"], [NEW_DN.encode()])

    def test_values_the_overlay_already_repointed_are_left_as_they_are(self):
        directory = _directory(_RefintDirectory, False)
        _MOD.migrate(directory, [_rename(True, [MEMBER])], False, _result())
        self.assertEqual(
            directory.entries[ADMIN_GROUP]["member"],
            [BIBER_DN.encode(), NEW_DN.encode()],
        )


class RepairTests(unittest.TestCase):
    def test_values_left_behind_after_the_move_are_repaired_without_a_move(self):
        directory = _directory(_Directory, True)
        result = _result()
        _MOD.migrate(directory, [_rename(False, [MEMBER_UID])], False, result)
        self.assertFalse([write for write in directory.writes if write[0] == "rename"])
        self.assertEqual(
            directory.entries[POSIX_GROUP]["memberUid"], [b"biber", b"platformadmin"]
        )
        self.assertEqual(result["renamed_dns"], [])


class NoOpTests(unittest.TestCase):
    def test_a_clean_plan_touches_nothing(self):
        directory = _directory(_Directory, False)
        result = _result()
        _MOD.migrate(directory, [], False, result)
        self.assertEqual(directory.writes, [])
        self.assertEqual(result, _result())

    def test_check_mode_reports_the_move_without_writing(self):
        directory = _directory(_Directory, False)
        result = _result()
        _MOD.migrate(directory, [_rename(True, [MEMBER])], True, result)
        self.assertEqual(directory.writes, [])
        self.assertIn(OLD_DN, directory.entries)
        self.assertEqual(result["renamed_dns"], [OLD_DN])


class FailureTests(unittest.TestCase):
    def test_a_refused_move_raises_before_any_group_changes(self):
        directory = _directory(_Directory, False)

        def refuse(dn, newrdn, delold):
            raise _LdapError("insufficient access")

        directory.rename_s = refuse
        with self.assertRaises(_LdapError):
            _MOD.migrate(directory, [_rename(True, [MEMBER])], False, _result())
        self.assertEqual(directory.writes, [])
        self.assertIn(OLD_DN.encode(), directory.entries[ADMIN_GROUP]["member"])

    def test_a_refused_group_write_raises_instead_of_being_swallowed(self):
        directory = _directory(_Directory, False)
        original = directory.modify_s

        def refuse(dn, changes):
            if dn == ADMIN_GROUP:
                raise _LdapError("insufficient access")
            original(dn, changes)

        directory.modify_s = refuse
        with self.assertRaises(_LdapError):
            _MOD.migrate(directory, [_rename(True, [MEMBER])], False, _result())


if __name__ == "__main__":
    unittest.main()
