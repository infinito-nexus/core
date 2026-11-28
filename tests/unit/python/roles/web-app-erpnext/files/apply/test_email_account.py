from __future__ import annotations

import unittest

from . import PROJECT_ROOT
from ._fake_frappe import FakeFrappe, run_script

SCRIPT = PROJECT_ROOT / "roles/web-app-erpnext/files/python/apply/email_account.py"
ACCOUNT = "Email Account"
NAME = "ERPNext Outbound"


def _env(*, port, tls, start_tls, auth):
    return {
        "SITE_NAME": "next.erp.infinito.example",
        "MAIL_FROM_NAME": "Infinito ERPNext",
        "MAIL_FROM_ADDRESS": "no-reply@infinito.example",
        "SMTP_HOST": "mail.infinito.example",
        "SMTP_PORT": str(port),
        "SMTP_TLS": str(tls).lower(),
        "SMTP_START_TLS": str(start_tls).lower(),
        "SMTP_AUTH_ENABLED": str(auth).lower(),
        "SMTP_USER": "no-reply@infinito.example",
        "SMTP_PASS": "submission-token",
    }


class TestEmailAccount(unittest.TestCase):
    def setUp(self) -> None:
        self.frappe = FakeFrappe()

    def _account(self, **transport):
        run_script(SCRIPT, self.frappe, _env(**transport))
        return self.frappe.records[ACCOUNT][NAME]

    def _run(self, **transport):
        account = self._account(**transport)
        return (
            account.get("smtp_port"),
            account.get("use_ssl_for_outgoing"),
            account.get("use_tls"),
        )

    def test_an_implicit_tls_relay_opens_the_session_inside_tls(self) -> None:
        self.assertEqual(
            (465, 1, 0), self._run(port=465, tls=True, start_tls=False, auth=True)
        )

    def test_a_starttls_relay_upgrades_a_plain_session(self) -> None:
        self.assertEqual(
            (587, 0, 1), self._run(port=587, tls=True, start_tls=True, auth=True)
        )

    def test_a_relay_without_tls_speaks_plain_smtp(self) -> None:
        self.assertEqual(
            (25, 0, 0), self._run(port=25, tls=False, start_tls=False, auth=False)
        )

    def test_a_relay_that_takes_no_login_is_sent_to_without_smtp_auth(self) -> None:
        account = self._account(port=25, tls=False, start_tls=False, auth=False)

        self.assertEqual(1, account.get("no_smtp_authentication"))

    def test_a_relay_that_takes_a_login_is_sent_to_with_smtp_auth(self) -> None:
        account = self._account(port=465, tls=True, start_tls=False, auth=True)

        self.assertEqual(0, account.get("no_smtp_authentication"))

    def test_a_relay_that_takes_no_login_keeps_no_password(self) -> None:
        self.frappe.seed(
            ACCOUNT,
            NAME,
            email_account_name=NAME,
            login_id="no-reply@infinito.example",
            password="submission-token",
        )

        account = self._account(port=25, tls=False, start_tls=False, auth=False)

        self.assertIsNone(account.get("password"))
        self.assertIsNone(account.get("login_id"))
        self.assertIn(
            ("remove_encrypted_password", ACCOUNT, NAME, "password"),
            self.frappe.calls,
        )

    def test_a_relay_that_takes_a_login_keeps_its_password(self) -> None:
        account = self._account(port=465, tls=True, start_tls=False, auth=True)

        self.assertEqual("submission-token", account.get("password"))
        self.assertEqual("no-reply@infinito.example", account.get("login_id"))
        self.assertNotIn("remove_encrypted_password", [c[0] for c in self.frappe.calls])

    def test_an_account_left_on_starttls_converges_to_the_relay_transport(
        self,
    ) -> None:
        self.frappe.seed(
            ACCOUNT,
            NAME,
            email_account_name=NAME,
            smtp_port=465,
            use_ssl_for_outgoing=0,
            use_tls=1,
        )

        transport = self._run(port=465, tls=True, start_tls=False, auth=True)

        self.assertEqual((465, 1, 0), transport)
        self.assertEqual([NAME], list(self.frappe.records[ACCOUNT]))

    def test_the_account_is_committed_and_the_site_closed(self) -> None:
        self._run(port=465, tls=True, start_tls=False, auth=True)

        self.assertTrue(self.frappe.db.committed)
        self.assertEqual(("destroy",), self.frappe.calls[-1])


if __name__ == "__main__":
    unittest.main()
