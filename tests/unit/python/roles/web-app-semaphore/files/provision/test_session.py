from __future__ import annotations

import contextlib
import io
import json
import signal
import stat
import time
import unittest
import unittest.mock as mock
from importlib.util import module_from_spec, spec_from_file_location

from utils.cache.files import read_text

from ._fake_provision import (
    CREDENTIALS,
    FILES,
    STATE_KEYS,
    WORKSPACE,
    TempCase,
    load,
)

session = load("provision.session")
opentofu = load("provision.opentofu")
ALARM_SECONDS = 600
DEADLINE_SECONDS = 0.5
REVOKE_SECONDS = 1.0
REVOKE_FAILURE = "OpenBao POST auth/token/revoke-self: HTTP 500"
BUDGET_FAILURE = "the run exceeded its time budget"
CATCH_ANY = "    except Exception as failure:\n"
CATCH_REMOTE_ONLY = "    except remote.RemoteError as failure:\n"
GUARDED_EXIT = (
    "    except BaseException:\n"
    "        revoke_after_failure(bao)\n"
    "        raise\n"
    "    with remote.alarm_deferred():\n"
    "        bao.revoke()\n"
)
FINALLY_EXIT = "    finally:\n        bao.revoke()\n"


class _Bao:
    """Args:
    error: what :meth:`revoke` raises, None for nothing.
    pause: the seconds :meth:`revoke` takes.
    """

    def __init__(self, error, pause):
        self.error = error
        self.pause = pause
        self.alarms = []

    def login(self, role, _jwt):
        return role

    def revoke(self):
        self.alarms.append(signal.getitimer(signal.ITIMER_REAL)[0])
        time.sleep(self.pause)
        if self.error is not None:
            raise self.error


class TestBackend(TempCase):
    def setUp(self):
        super().setUp()
        self.config = {"cafile": "", "state": "https://s3.example.org"}

    def test_values_are_escaped_for_hcl(self):
        self.assertEqual(session._hcl('a${b}%{c}"'), '"a$${b}%%{c}\\""')

    def test_the_backend_file_is_private_and_written_once(self):
        keys = {**STATE_KEYS, "secret_key": "s${x}"}
        path = session.write_backend(self.root, self.config, "b", "SO/1.tfstate", keys)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        text = path.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        self.assertIn('secret_key = "s$${x}"\n', text)
        self.assertIn('endpoints = {\n  s3 = "https://s3.example.org"\n}\n', text)
        self.assertNotIn("custom_ca_bundle", text)
        with self.assertRaises(FileExistsError):
            session.write_backend(self.root, self.config, "b", "k", keys)

    def test_a_ca_file_reaches_the_backend(self):
        config = {**self.config, "cafile": "/etc/ssl/ca.pem"}
        path = session.write_backend(self.root, config, "b", "k", STATE_KEYS)
        text = path.read_text()  # nocheck: cache-read tempdir
        self.assertIn('custom_ca_bundle = "/etc/ssl/ca.pem"\n', text)


class TestEncryption(unittest.TestCase):
    def test_state_and_plan_are_enforced_with_the_workspace_transit_key(self):
        document = json.loads(session.encryption(WORKSPACE))
        key = document["key_provider"]["openbao"]["workspace"]
        self.assertEqual(key["key_name"], f"{WORKSPACE}-provision")
        self.assertEqual(key["transit_engine_path"], "/transit")
        for target in ("state", "plan"):
            self.assertEqual(
                document[target],
                {"method": "${method.aes_gcm.workspace}", "enforced": True},
            )


class TestCredentials(TempCase):
    def test_every_credential_name_is_cleared(self):
        names = session.credential_names(CREDENTIALS)
        self.assertLessEqual(
            {
                "AWS_ACCESS_KEY_ID",
                "CLOUDFLARE_API_TOKEN",
                "DNS_UPDATE_KEYSECRET",
                "HCLOUD_TOKEN",
                "IONOS_TOKEN",
                "OS_APPLICATION_CREDENTIAL_SECRET",
                "OS_AUTH_TYPE",
                "PROXMOX_VE_API_TOKEN",
                "INCUS_ADDR",
                "INCUS_CONF",
            },
            names,
        )


class TestOpened(TempCase):
    def setUp(self):
        super().setUp()
        signal.setitimer(signal.ITIMER_REAL, ALARM_SECONDS)
        self.addCleanup(signal.setitimer, signal.ITIMER_REAL, 0)

    def planted(self, old, new):
        """Args:
            old: a part of ``session.py`` that must occur.
            new: what replaces it.

        Returns:
            ``provision.session`` loaded from the planted source.
        """
        text = read_text(str(FILES / "python" / "provision" / "session.py"))
        planted = text.replace(old, new)
        self.assertNotEqual(planted, text)
        path = self.root / "session.py"
        path.write_text(planted, encoding="utf-8")
        spec = spec_from_file_location("provision.session", path)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def over_budget(self):
        def raise_budget(_signum, _frame):
            raise opentofu.BudgetError(BUDGET_FAILURE)

        previous = signal.signal(signal.SIGALRM, raise_budget)
        self.addCleanup(signal.signal, signal.SIGALRM, previous)
        self.addCleanup(signal.setitimer, signal.ITIMER_REAL, 0)

    def leave(self, module, bao, error=None, alarm=None):
        """Args:
        module: a loaded ``provision.session``.
        bao: the client :func:`opened` logs in with.
        error: what the block raises, None for nothing.
        alarm: the seconds the block arms the run budget's timer with right
            before it raises, None to keep the timer of :meth:`setUp`.
        """
        with (
            mock.patch.object(module.remote, "OpenBao", return_value=bao),
            mock.patch.object(module, "Session"),
            module.opened(
                {"SEMAPHORE_JWT": "jwt"},
                {"openbao": "", "cafile": ""},
                CREDENTIALS,
                {"workspace": WORKSPACE},
                self.root,
                "key",
                "provision",
            ),
        ):
            if alarm is not None:
                signal.setitimer(signal.ITIMER_REAL, alarm)
            if error is not None:
                raise error

    def test_the_revoke_takes_no_alarm_on_either_exit(self):
        for error in (None, session.inputs.RefusedError("refused")):
            with self.subTest(error=error):
                bao = _Bao(None, 0)
                with contextlib.suppress(session.inputs.RefusedError):
                    self.leave(session, bao, error)
                self.assertEqual(bao.alarms, [0.0])

    def test_a_failed_revoke_keeps_the_exception_of_the_block(self):
        bao = _Bao(session.remote.RemoteError(REVOKE_FAILURE), 0)
        stderr = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            self.assertRaises(session.inputs.RefusedError),
        ):
            self.leave(session, bao, session.inputs.RefusedError("refused"))
        self.assertIn(REVOKE_FAILURE, stderr.getvalue())
        self.assertEqual(bao.alarms, [0.0])

    def test_a_failed_revoke_after_a_clean_block_fails_the_run(self):
        bao = _Bao(session.remote.RemoteError(REVOKE_FAILURE), 0)
        with self.assertRaises(session.remote.RemoteError):
            self.leave(session, bao)

    def test_negative_control_a_revoke_in_finally_replaces_the_refusal(self):
        module = self.planted(GUARDED_EXIT, FINALLY_EXIT)
        bao = _Bao(module.remote.RemoteError(REVOKE_FAILURE), 0)
        with self.assertRaises(module.remote.RemoteError):
            self.leave(module, bao, module.inputs.RefusedError("refused"))
        self.assertGreater(bao.alarms[0], 0)

    def test_a_budget_passing_during_the_revoke_keeps_the_refusal(self):
        self.over_budget()
        bao = _Bao(None, REVOKE_SECONDS)
        refusal = session.inputs.RefusedError("refused")
        stderr = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            self.assertRaises(session.inputs.RefusedError),
        ):
            self.leave(session, bao, refusal, DEADLINE_SECONDS)
        self.assertIn(BUDGET_FAILURE, stderr.getvalue())
        self.assertEqual(bao.alarms, [0.0])

    def test_negative_control_a_remote_error_only_catch_lets_the_budget_win(self):
        module = self.planted(CATCH_ANY, CATCH_REMOTE_ONLY)
        self.over_budget()
        bao = _Bao(None, REVOKE_SECONDS)
        refusal = module.inputs.RefusedError("refused")
        with self.assertRaises(opentofu.BudgetError):
            self.leave(module, bao, refusal, DEADLINE_SECONDS)


if __name__ == "__main__":
    unittest.main()
