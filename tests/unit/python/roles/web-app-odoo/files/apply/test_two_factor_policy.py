from __future__ import annotations

import io
import os
import runpy
import sys
import types
import unittest
import unittest.mock as mock
from contextlib import redirect_stdout

from utils.cache.files import PROJECT_ROOT

SCRIPT_PATH = (
    PROJECT_ROOT / "roles/web-app-odoo/files/python/apply/two_factor_policy.py"
)
KEY = "auth_totp.policy"
OWNER = "infinito.auth_totp_policy_by_deploy"
NONE = "none"
POLICY = "all_required"
ADMIN_POLICY = "employee_required"
NO_SESSION = object()


class UserError(Exception):
    pass


class TestTwoFactorPolicy(unittest.TestCase):
    def _run(
        self,
        state: str,
        current,
        marker=False,
        smtp_error: Exception | None = None,
        session=NO_SESSION,
    ):
        """Run the applier against an ``ir.config_parameter`` store.

        Args:
            state: ``ODOO_2FA_STATE``.
            current: the stored ``auth_totp.policy``, False when unset.
            marker: the stored ownership marker, False when unset.
            smtp_error: what ``ir.mail_server._connect__`` raises, if anything.
            session: what ``ir.mail_server._connect__`` returns, if not a mock.

        Returns:
            The printed lines, the store after the run, the mail server and env.
        """
        store = {KEY: current, OWNER: marker}
        parameters = mock.MagicMock(name="ir.config_parameter")
        parameters.sudo.return_value = parameters
        parameters.get_param.side_effect = lambda key: store.get(key, False)
        parameters.set_param.side_effect = store.__setitem__
        mail_server = mock.MagicMock(name="ir.mail_server")
        if smtp_error is not None:
            mail_server._connect__.side_effect = smtp_error
        if session is not NO_SESSION:
            mail_server._connect__.return_value = session
        env = mock.MagicMock(name="env")
        env.__getitem__.side_effect = {
            "ir.config_parameter": parameters,
            "ir.mail_server": mail_server,
        }.__getitem__
        exceptions = types.ModuleType("odoo.exceptions")
        exceptions.UserError = UserError
        odoo = types.ModuleType("odoo")
        odoo.exceptions = exceptions
        buf = io.StringIO()
        with (
            mock.patch.dict(sys.modules, {"odoo": odoo, "odoo.exceptions": exceptions}),
            mock.patch.dict(
                os.environ, {"ODOO_2FA_STATE": state, "ODOO_2FA_POLICY": POLICY}
            ),
            redirect_stdout(buf),
        ):
            runpy.run_path(
                str(SCRIPT_PATH), init_globals={"env": env}, run_name="__main__"
            )
        return buf.getvalue().split("\n"), store, mail_server, env

    def test_enforce_writes_the_policy_and_the_marker_after_an_smtp_session(
        self,
    ) -> None:
        lines, store, mail_server, env = self._run("enforce", False)
        mail_server._connect__.assert_called_once_with()
        mail_server._connect__.return_value.close.assert_called_once_with()
        self.assertEqual({KEY: POLICY, OWNER: NONE}, store)
        env.cr.commit.assert_called_once_with()
        env.registry.signal_changes.assert_called_once_with()
        self.assertIn("MAIL=ok", lines)
        self.assertIn("TWO_FACTOR_POLICY_CHANGED", lines)

    def test_enforce_keeps_an_admins_policy_in_the_marker(self) -> None:
        _lines, store, _mail, _env = self._run("enforce", ADMIN_POLICY)
        self.assertEqual({KEY: POLICY, OWNER: ADMIN_POLICY}, store)

    def test_an_owned_policy_stays_unchanged(self) -> None:
        for marker in (NONE, ADMIN_POLICY):
            with self.subTest(marker=marker):
                lines, store, _mail, env = self._run("enforce", POLICY, marker)
                self.assertEqual({KEY: POLICY, OWNER: marker}, store)
                env.registry.signal_changes.assert_not_called()
                self.assertIn("TWO_FACTOR_POLICY_UNCHANGED", lines)

    def test_an_admins_equal_policy_is_not_claimed(self) -> None:
        lines, store, _mail, _env = self._run("enforce", POLICY)
        self.assertEqual({KEY: POLICY, OWNER: False}, store)
        self.assertIn("TWO_FACTOR_POLICY_UNCHANGED", lines)

    def test_a_failing_smtp_session_keeps_an_owned_policy(self) -> None:
        for error in (
            OSError("refused"),
            UserError("Missing SMTP Server"),
            RuntimeError("unexpected"),
        ):
            with self.subTest(error=type(error).__name__):
                lines, store, _mail, _env = self._run(
                    "enforce", POLICY, NONE, smtp_error=error
                )
                self.assertEqual({KEY: POLICY, OWNER: NONE}, store)
                self.assertIn(f"MAIL=failed {type(error).__name__}", lines)
                self.assertIn("TWO_FACTOR_POLICY_UNCHANGED", lines)

    def test_a_failing_smtp_session_prints_only_the_error_class(self) -> None:
        lines, _store, _mail, _env = self._run(
            "enforce", False, smtp_error=RuntimeError("smtp://user:secret@host")
        )
        self.assertFalse(any("secret" in line for line in lines))
        self.assertIn("MAIL=failed RuntimeError", lines)

    def test_no_smtp_session_holds_the_policy(self) -> None:
        lines, store, _mail, _env = self._run("enforce", False, session=None)
        self.assertEqual({KEY: False, OWNER: False}, store)
        self.assertIn("MAIL=failed ConnectionError", lines)

    def test_a_failing_smtp_session_never_switches_the_policy_on(self) -> None:
        _lines, store, _mail, _env = self._run("enforce", False, smtp_error=OSError())
        self.assertEqual({KEY: False, OWNER: False}, store)

    def test_releasing_restores_the_policy_the_deploy_replaced(self) -> None:
        for state in ("offer", "off", "hold"):
            for marker, restored in ((NONE, False), (ADMIN_POLICY, ADMIN_POLICY)):
                with self.subTest(state=state, marker=marker):
                    lines, store, mail_server, env = self._run(state, POLICY, marker)
                    self.assertEqual({KEY: restored, OWNER: False}, store)
                    mail_server._connect__.assert_not_called()
                    env.registry.signal_changes.assert_called_once_with()
                    self.assertIn("TWO_FACTOR_POLICY_CHANGED", lines)

    def test_a_policy_without_the_marker_stays(self) -> None:
        for state in ("offer", "off", "hold"):
            for current in (POLICY, ADMIN_POLICY):
                with self.subTest(state=state, current=current):
                    lines, store, _mail, _env = self._run(state, current)
                    self.assertEqual({KEY: current, OWNER: False}, store)
                    self.assertIn("TWO_FACTOR_POLICY_UNCHANGED", lines)

    def test_a_policy_an_admin_changed_keeps_its_value_and_drops_the_marker(
        self,
    ) -> None:
        _lines, store, _mail, _env = self._run("off", ADMIN_POLICY, NONE)
        self.assertEqual({KEY: ADMIN_POLICY, OWNER: False}, store)


if __name__ == "__main__":
    unittest.main()
