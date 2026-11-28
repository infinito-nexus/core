from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import signal
import time
import unittest
import unittest.mock as mock

from ._fake_provision import (
    KEYSTONE_OWN_RECORD,
    KEYSTONE_SUBJECT,
    KEYSTONE_TOKENS,
    SCS_CREDENTIAL_ID,
    SCS_CREDENTIAL_SECRET,
    SCS_WRONG_SECRET,
    FakeKeystone,
    keystone_record,
    keystone_token,
    load,
    secret_parts,
)

keystone = load("provision.keystone")

CHECKED = [
    ("POST", KEYSTONE_TOKENS),
    ("GET", KEYSTONE_OWN_RECORD),
    ("DELETE", KEYSTONE_TOKENS),
]
MINTED = (201, {"x-subject-token": KEYSTONE_SUBJECT}, b"{}")
REVOKE_PAUSE = 0.5


def scripted(*answers):
    """Args:
        answers: the ``(status, headers, body)`` the calls get, in order.

    Returns:
        A stand-in for :func:`remote.exchange` and the list of
        ``(method, url)`` it was called with.
    """
    calls = []
    queue = list(answers)

    def exchange(url, method, _headers, _body, _cafile, _timeout):
        calls.append((method, url))
        return queue.pop(0)

    return exchange, calls


def passing(revoked):
    """Args:
        revoked: the ``(status, headers, body)`` the revoke of the token gets.

    Returns:
        Keystone's answers to a check the credential passes, by method.
    """
    token = json.dumps({"token": keystone_token()}).encode()
    record = json.dumps({"application_credential": keystone_record()}).encode()
    return {
        "POST": (201, MINTED[1], token),
        "GET": (200, {}, record),
        "DELETE": revoked,
    }


class TestKeystoneContract(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime.now(dt.UTC)
        self.deadline = self.now + dt.timedelta(hours=2)
        self.keystone = FakeKeystone(keystone_token(), keystone_record())
        self.addCleanup(self.keystone.stop)

    def check(self, secret):
        """Args:
            secret: the secret the check presents.

        Returns:
            ``(refusal, output)``: the refusal message, empty for a passed
            check, and everything the check printed.
        """
        output = io.StringIO()
        refusal = ""
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            try:
                keystone.keystone_contract(
                    self.keystone.auth_url, SCS_CREDENTIAL_ID, secret, self.deadline
                )
            except keystone.inputs.RefusedError as error:
                refusal = str(error)
        return refusal, output.getvalue()

    def run_check(self, exchange):
        """Args:
        exchange: the stand-in for :func:`remote.exchange` that answers
            the check of the valid credential.
        """
        with mock.patch.object(keystone, "exchange", exchange):
            keystone.keystone_contract(
                self.keystone.auth_url,
                SCS_CREDENTIAL_ID,
                SCS_CREDENTIAL_SECRET,
                self.deadline,
            )

    def scripted_check(self, *answers):
        """Args:
            answers: the ``(status, headers, body)`` Keystone gives, in order.

        Returns:
            The ``(method, url)`` calls the check made before it raised.
        """
        exchange, calls = scripted(*answers)
        self.run_check(exchange)
        return calls

    def keystone_time(self, delta):
        return (self.now + delta).replace(tzinfo=None).isoformat()

    def test_scs_credential_contract(self):
        cases = {
            "does not authenticate at Keystone 127.0.0.1: HTTP 401": (
                SCS_WRONG_SECRET,
                {},
                {},
            ),
            "is unrestricted, so it could create further credentials": (
                SCS_CREDENTIAL_SECRET,
                {},
                {"unrestricted": True},
            ),
            "is scoped to no project": (SCS_CREDENTIAL_SECRET, {"project": None}, {}),
            "is scoped to more than one project": (
                SCS_CREDENTIAL_SECRET,
                {},
                {"project_id": "p-other-project"},
            ),
            "before the run's time budget ends at": (
                SCS_CREDENTIAL_SECRET,
                {},
                {"expires_at": self.keystone_time(dt.timedelta(minutes=30))},
            ),
        }
        for rule, (secret, token, record) in cases.items():
            with self.subTest(rule=rule):
                self.keystone.token = keystone_token() | token
                self.keystone.record = keystone_record() | record
                self.keystone.requests.clear()
                self.keystone.revoked = 0
                refusal, output = self.check(secret)
                self.assertIn(rule, refusal)
                self.assertEqual(output, "")
                self.assertEqual(
                    secret_parts(
                        refusal, SCS_CREDENTIAL_SECRET, KEYSTONE_SUBJECT, secret
                    ),
                    [],
                )
                minted = secret == SCS_CREDENTIAL_SECRET
                self.assertEqual(
                    self.keystone.requests, CHECKED if minted else CHECKED[:1]
                )
                self.assertEqual(self.keystone.revoked, int(minted))

    def test_a_domain_scope_beside_the_project_is_more_than_one_project(self):
        self.keystone.token = keystone_token() | {"domain": {"id": "default"}}
        self.assertIn("more than one project", self.check(SCS_CREDENTIAL_SECRET)[0])

    def test_negative_control_a_restricted_project_credential_passes(self):
        for expires in (None, self.keystone_time(dt.timedelta(hours=3))):
            with self.subTest(expires=expires):
                self.keystone.record = keystone_record() | {"expires_at": expires}
                self.keystone.requests.clear()
                self.assertEqual(self.check(SCS_CREDENTIAL_SECRET), ("", ""))
                self.assertEqual(self.keystone.requests, CHECKED)
        self.assertEqual(self.keystone.revoked, 2)

    def test_only_401_and_403_refuse_the_credential(self):
        for status in keystone.REFUSED_LOGIN:
            with (
                self.subTest(status=status),
                self.assertRaisesRegex(keystone.inputs.RefusedError, f"HTTP {status}"),
            ):
                self.scripted_check((status, {}, b""))
        for status in (400, 404, 429, 500, 503):
            with (
                self.subTest(status=status),
                self.assertRaisesRegex(keystone.RemoteError, f"HTTP {status}$"),
            ):
                self.scripted_check((status, {}, b""))

    def test_an_answer_without_its_document_fails_and_revokes(self):
        token = json.dumps({"token": keystone_token()}).encode()
        cases = {
            "answered without token": [MINTED, (204, {}, b"")],
            "answered without application_credential": [
                (201, MINTED[1], token),
                (200, {}, b'{"other": {}}'),
                (204, {}, b""),
            ],
        }
        for message, answers in cases.items():
            exchange, calls = scripted(*answers)
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(keystone.RemoteError, message),
            ):
                self.run_check(exchange)
            self.assertEqual(calls[-1][0], "DELETE")

    def test_a_token_keystone_keeps_fails_the_check(self):
        with self.assertRaisesRegex(
            keystone.RemoteError, "kept the token of the check"
        ):
            self.scripted_check(*passing((500, {}, b"")).values())

    def test_the_revoke_runs_with_the_budget_alarm_disarmed(self):
        previous = signal.signal(signal.SIGALRM, lambda *_: None)
        self.addCleanup(signal.signal, signal.SIGALRM, previous)
        self.addCleanup(signal.alarm, 0)
        answers = passing((204, {}, b""))
        armed = {}
        timeouts = {}

        def exchange(_url, method, _headers, _body, _cafile, timeout):
            armed[method] = signal.getitimer(signal.ITIMER_REAL)[0]
            timeouts[method] = timeout
            return answers[method]

        signal.alarm(100)
        self.run_check(exchange)
        self.assertGreater(armed["GET"], 0)
        self.assertEqual(armed["DELETE"], 0)
        self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0], 90)
        self.assertEqual(
            timeouts,
            {
                "POST": keystone.TIMEOUT,
                "GET": keystone.TIMEOUT,
                "DELETE": keystone.REVOKE_TIMEOUT,
            },
        )

    def test_a_budget_that_ends_during_the_revoke_fires_once_it_is_done(self):
        class OverBudgetError(Exception):
            pass

        def over(*_):
            raise OverBudgetError

        previous = signal.signal(signal.SIGALRM, over)
        self.addCleanup(signal.signal, signal.SIGALRM, previous)
        self.addCleanup(signal.alarm, 0)
        answers = passing((204, {}, b""))
        revoked = []

        def exchange(_url, method, _headers, _body, _cafile, _timeout):
            if method == "DELETE":
                time.sleep(REVOKE_PAUSE)
                revoked.append(method)
            return answers[method]

        signal.setitimer(signal.ITIMER_REAL, REVOKE_PAUSE / 2)
        with self.assertRaises(OverBudgetError):
            self.run_check(exchange)
        self.assertEqual(revoked, ["DELETE"])

    def test_a_failed_revoke_keeps_the_error_that_ended_the_check(self):
        answers = passing((500, {}, b""))

        def exchange(_url, method, _headers, _body, _cafile, _timeout):
            if method == "GET":
                raise SystemExit(143)
            return answers[method]

        stderr = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as stop,
        ):
            self.run_check(exchange)
        self.assertEqual(stop.exception.code, 143)
        self.assertIn("kept the token of the check: HTTP 500", stderr.getvalue())
        self.assertNotIn(SCS_CREDENTIAL_SECRET, stderr.getvalue())
        self.assertNotIn(KEYSTONE_SUBJECT, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
