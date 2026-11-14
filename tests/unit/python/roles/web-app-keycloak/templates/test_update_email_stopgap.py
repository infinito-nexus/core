from __future__ import annotations

import unittest
from unittest import mock

from .test_realm_import_json import (
    LDAP_PROVIDER,
    MAILBOX,
    ROLE_VARS,
    SMTP,
    drifted_required_actions,
    profile_of,
    realm_for,
    reconciled,
    role_flag,
    update_email_of,
)

FLAG = "KEYCLOAK_EMAIL_UPDATE_ENABLED"
PRE_STOPGAP = "{{ KEYCLOAK_EMAIL_SMTP | bool }}"
WITHOUT_LDAP = {"KEYCLOAK_LDAP_ENABLED": False}
LDAP_REALM_ON = "UPDATE_EMAIL is on in a realm that federates LDAP"
DIRECT_EDIT = "the user edits the address directly while UPDATE_EMAIL is off"


def update_email_findings(realm: dict) -> list[str]:
    """What sends an LDAP user into the failing UPDATE_EMAIL or lets a user skip it.

    Args:
        realm: the rendered realm import.

    Returns:
        LDAP_REALM_ON when an LDAP realm enables UPDATE_EMAIL, DIRECT_EDIT when
        the user may edit ``email`` although UPDATE_EMAIL is off.
    """
    findings = []
    enabled = update_email_of(realm)["enabled"]
    if enabled and LDAP_PROVIDER in realm["components"]:
        findings.append(LDAP_REALM_ON)
    if not enabled and "user" in profile_of(realm)["email"]["permissions"]["edit"]:
        findings.append(DIRECT_EDIT)
    return findings


class TestUpdateEmailStopgap(unittest.TestCase):
    def test_the_flag_needs_smtp_and_a_realm_without_ldap(self) -> None:
        for smtp, ldap, expected in (
            (True, False, True),
            (True, True, False),
            (False, False, False),
            (False, True, False),
        ):
            with self.subTest(smtp=smtp, ldap=ldap):
                context = {"KEYCLOAK_EMAIL_SMTP": smtp, "KEYCLOAK_LDAP_ENABLED": ldap}
                self.assertIs(expected, role_flag(FLAG, context))

    def test_an_ldap_realm_with_smtp_turns_update_email_off_and_locks_the_address(
        self,
    ) -> None:
        for name, overrides in (("external", SMTP), ("mailbox", {**MAILBOX, **SMTP})):
            with self.subTest(policy=name):
                realm = realm_for(overrides)
                self.assertIn(LDAP_PROVIDER, realm["components"])
                self.assertIs(False, update_email_of(realm)["enabled"])
                self.assertEqual(
                    ["admin"], profile_of(realm)["email"]["permissions"]["edit"]
                )
                self.assertEqual([], update_email_findings(realm))

    def test_a_realm_without_ldap_keeps_update_email_with_smtp(self) -> None:
        realm = realm_for({**SMTP, **WITHOUT_LDAP})
        self.assertNotIn(LDAP_PROVIDER, realm["components"])
        self.assertIs(True, update_email_of(realm)["enabled"])
        self.assertEqual(
            ["admin", "user"], profile_of(realm)["email"]["permissions"]["edit"]
        )
        self.assertEqual([], update_email_findings(realm))

    def test_the_pre_stopgap_expression_fails_the_check(self) -> None:
        with mock.patch.dict(ROLE_VARS, {FLAG: PRE_STOPGAP}):
            realm = realm_for(SMTP)
        self.assertEqual([LDAP_REALM_ON], update_email_findings(realm))

    def test_switching_update_email_off_without_the_lock_fails_the_check(
        self,
    ) -> None:
        realm = realm_for({**SMTP, **WITHOUT_LDAP})
        update_email_of(realm)["enabled"] = False
        self.assertEqual([DIRECT_EDIT], update_email_findings(realm))

    def test_an_existing_ldap_realm_converges_update_email_off(self) -> None:
        self.assertIn("UPDATE_EMAIL", ROLE_VARS["KEYCLOAK_RECONCILED_REQUIRED_ACTIONS"])
        with mock.patch.dict(ROLE_VARS, {FLAG: PRE_STOPGAP}):
            live = reconciled(realm_for(SMTP))
        drifted = drifted_required_actions(reconciled(realm_for(SMTP)), live)
        self.assertEqual(["UPDATE_EMAIL"], [a["alias"] for a in drifted])
        self.assertIs(False, drifted[0]["enabled"])

    def test_a_converged_ldap_realm_shows_no_drift(self) -> None:
        desired = reconciled(realm_for(SMTP))
        self.assertEqual([], drifted_required_actions(desired, desired))


if __name__ == "__main__":
    unittest.main()
