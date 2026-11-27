import contextlib
import imaplib
import importlib.util
import io
import json
import shlex
import smtplib
import ssl
import subprocess
import unittest
import unittest.mock as mock
import urllib.error

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_TESTS

from . import PROJECT_ROOT

_ROLE = PROJECT_ROOT / "roles/web-app-stalwart"
_ENV = {
    "STALWART_ADMIN_USER": "admin",
    "STALWART_ADMIN_PASSWORD": 'pa ss"word',
    "STALWART_CONTAINER": "stalwart-cid",
    "STALWART_JMAP_URL": "http://localhost:8080/jmap/",
}


def _load_module():
    path = PROJECT_ROOT / "roles/web-app-stalwart/files/test/probe/stalwart.py"
    spec = importlib.util.spec_from_file_location("stalwart_probe", str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


_M = _load_module()


def _probe(*outcomes):
    calls = iter(outcomes)

    def probe():
        outcome = next(calls)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return probe


class TestWaitFor(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(_M.time, "sleep")
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, probe):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = _M.wait_for("probe", probe)
        return result, out.getvalue(), err.getvalue()

    def test_transport_error_counts_as_not_yet(self):
        result, out, _ = self._run(_probe(ConnectionRefusedError("refused"), True))
        self.assertTrue(result)
        self.assertIn("ok: probe", out)

    def test_imap_abort_counts_as_not_yet(self):
        result, _, _ = self._run(_probe(imaplib.IMAP4.abort("socket error"), True))
        self.assertTrue(result)

    def test_imap_login_error_counts_as_not_yet(self):
        result, _, _ = self._run(_probe(imaplib.IMAP4.error("LOGIN failed"), True))
        self.assertTrue(result)

    def test_tls_and_http_errors_count_as_not_yet(self):
        probe = _probe(ssl.SSLError("EOF"), urllib.error.URLError("reset"), True)
        result, _, _ = self._run(probe)
        self.assertTrue(result)

    def test_smtp_error_counts_as_not_yet(self):
        result, _, _ = self._run(_probe(smtplib.SMTPServerDisconnected("gone"), True))
        self.assertTrue(result)

    def test_exhausted_budget_fails_with_the_last_error(self):
        outcomes = [False] * (_M.POLL_ATTEMPTS - 1) + [TimeoutError("timed out")]
        result, _, err = self._run(_probe(*outcomes))
        self.assertFalse(result)
        self.assertIn("FAIL: probe (last error: TimeoutError: timed out)", err)

    def test_errors_share_the_poll_budget(self):
        probe = mock.Mock(side_effect=OSError("down"))
        result, _, _ = self._run(probe)
        self.assertFalse(result)
        self.assertEqual(probe.call_count, _M.POLL_ATTEMPTS)

    def test_fail_without_error_names_none(self):
        result, _, err = self._run(lambda: False)
        self.assertFalse(result)
        self.assertIn("FAIL: probe\n", err)

    def test_non_transport_error_propagates(self):
        with self.assertRaises(KeyError):
            self._run(_probe(KeyError("primaryAccounts")))


class TestSend(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(_M.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _send(self, smtp):
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(_M.smtplib, "SMTP", smtp),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            _M.send("a@example.org", "b@example.org", "subject")
        return out.getvalue(), err.getvalue()

    def test_send_retries_after_a_transport_error(self):
        session = mock.MagicMock()
        smtp = mock.Mock(side_effect=[ConnectionRefusedError("refused"), session])
        out, err = self._send(smtp)
        self.assertEqual(smtp.call_count, 2)
        session.__enter__.return_value.send_message.assert_called_once()
        self.assertIn("retry: subject -> b@example.org", err)
        self.assertIn("sent: subject -> b@example.org", out)

    def test_send_raises_once_the_budget_is_spent(self):
        smtp = mock.Mock(side_effect=smtplib.SMTPServerDisconnected("gone"))
        with self.assertRaises(smtplib.SMTPServerDisconnected):
            self._send(smtp)
        self.assertEqual(smtp.call_count, _M.POLL_ATTEMPTS)


class TestHttp(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(_M.os.environ, _ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, completed):
        run = mock.Mock(return_value=completed)
        with mock.patch.object(_M.subprocess, "run", run):
            return run, _M.http("session", {"k": "v"}, "biber@example.org")

    def test_jmap_runs_inside_the_stalwart_container(self):
        done = subprocess.CompletedProcess([], 0, stdout='{"ok": 1}', stderr="")
        run, body = self._run(done)
        self.assertEqual(body, {"ok": 1})
        argv = run.call_args.args[0]
        self.assertEqual(argv[:5], ["container", "exec", "-i", "stalwart-cid", "curl"])
        self.assertEqual(argv[-1], "http://localhost:8080/jmap/session")
        self.assertNotIn('pa ss"word', " ".join(argv))

    def test_credentials_and_payload_travel_as_curl_config_on_stdin(self):
        done = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
        run, _ = self._run(done)
        config = run.call_args.kwargs["input"].splitlines()
        self.assertEqual(
            config[0], "user = " + json.dumps('biber@example.org%admin:pa ss"word')
        )
        self.assertEqual(config[1], "data-binary = " + json.dumps('{"k": "v"}'))

    def test_a_failed_call_is_a_transport_error_the_poll_retries(self):
        done = subprocess.CompletedProcess([], 7, stdout="", stderr="refused")
        with self.assertRaises(_M.TRANSIENT_ERRORS) as caught:
            self._run(done)
        self.assertIn("curl exited 7", str(caught.exception))

    def test_a_hung_exec_is_a_transport_error_the_poll_retries(self):
        self.assertTrue(issubclass(subprocess.TimeoutExpired, _M.TRANSIENT_ERRORS))


class TestCliPlacement(unittest.TestCase):
    def test_the_cli_test_runs_on_the_node_of_the_stalwart_task(self):
        tests = load_yaml_any(_ROLE / ROLE_FILE_META_TESTS)
        self.assertEqual(tests["cli"]["container_service_key"], "stalwart")

    def test_the_probe_gets_the_resolved_container_and_its_inner_jmap_url(self):
        keys = ("STALWART_CONTAINER", "STALWART_JMAP_URL")
        source = read_text(str(_ROLE / "templates/test.env.j2"))
        lines = [line for line in source.splitlines() if line.startswith(keys)]
        env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
        env.filters["quote"] = shlex.quote
        rendered = env.from_string("\n".join(lines)).render(
            CLI_LOCAL_CID=_ENV["STALWART_CONTAINER"],
            STALWART_JMAP_URL=_ENV["STALWART_JMAP_URL"],
        )
        values = dict(line.split("=", 1) for line in rendered.splitlines())
        self.assertEqual(values, {key: _ENV[key] for key in keys})


if __name__ == "__main__":
    unittest.main()
