from __future__ import annotations

import unittest

from infinito_elector_src.openldap import OpenLDAPRole
from infinito_elector_src.roles import RoleError

from . import _NAME  # noqa: F401  side-effect import registers infinito_elector_src


class FakeLdap:
    def __init__(self, csns: dict[str, list[str]], read_only: str = "TRUE") -> None:
        self.csns = csns
        self.read_only = read_only
        self.modifications: list[str] = []

    def __call__(self, argv, stdin) -> str:
        if argv[0] == "ldapmodify":
            self.modifications.append(stdin)
            return ""
        if "olcReadOnly" in argv:
            return f"dn: x\nolcReadOnly: {self.read_only}\n"
        target = argv[argv.index("-H") + 1]
        if target not in self.csns:
            raise RoleError("unreachable")
        return "dn: dc=example\n" + "".join(
            f"contextCSN: {c}\n" for c in self.csns[target]
        )


def _role(fake: FakeLdap) -> OpenLDAPRole:
    return OpenLDAPRole(
        host_id="l1",
        peers=["l1", "l2"],
        database_dn="olcDatabase={1}mdb,cn=config",
        suffix="dc=example",
        peer_url=lambda host: f"ldap://openldap-{host}",
        bind_dn="cn=elector",
        bind_password_file="/run/secrets/pw",
        run=fake,
    )


class TestOpenLDAPRole(unittest.TestCase):
    def test_ready_when_context_csn_equals_a_peer(self) -> None:
        fake = FakeLdap(
            {
                "ldapi:///": ["20261008#000001"],
                "ldap://openldap-l2": ["20261008#000001"],
            }
        )
        self.assertTrue(_role(fake).is_ready_to_compete())

    def test_not_ready_while_refreshing(self) -> None:
        fake = FakeLdap(
            {
                "ldapi:///": ["20261007#000001"],
                "ldap://openldap-l2": ["20261008#000001"],
            }
        )
        self.assertFalse(_role(fake).is_ready_to_compete())

    def test_ready_alone_on_cold_start(self) -> None:
        self.assertTrue(_role(FakeLdap({"ldapi:///": ["x"]})).is_ready_to_compete())

    def test_read_only_toggle_via_ldapi(self) -> None:
        fake = FakeLdap({"ldapi:///": []})
        role = _role(fake)
        self.assertFalse(role.is_writable())
        role.become_writer()
        role.become_read_only()
        self.assertIn("olcReadOnly: FALSE", fake.modifications[0])
        self.assertIn("olcReadOnly: TRUE", fake.modifications[1])
        self.assertIn("dn: olcDatabase={1}mdb,cn=config", fake.modifications[0])
        fake.read_only = "FALSE"
        self.assertTrue(role.is_writable())

    def test_rank_is_the_newest_csn(self) -> None:
        fake = FakeLdap(
            {
                "ldapi:///": ["20261007#a", "20261008#b"],
                "ldap://openldap-l2": ["20261006#c"],
            }
        )
        role = _role(fake)
        self.assertEqual(role.rank(), "20261008#b")
        self.assertEqual(role.peer_ranks(), {"l2": "20261006#c"})


if __name__ == "__main__":
    unittest.main()
