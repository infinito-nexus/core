#!/usr/bin/env python3
import importlib.util
import urllib.error
from unittest import TestCase, main, mock

from . import PROJECT_ROOT

ONION = "abcdefghij.onion"


def load_target_module():
    script_path = (
        PROJECT_ROOT
        / "roles"
        / "svc-net-tor"
        / "files"
        / "python"
        / "onion_self_reach.py"
    )

    if not script_path.is_file():
        raise FileNotFoundError(f"Target script not found at: {script_path}")

    spec = importlib.util.spec_from_file_location(
        "onion_self_reach_script", script_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


SCRIPT = load_target_module()


def _urlopen_raising(exc):
    return mock.patch.object(SCRIPT.urllib.request, "urlopen", side_effect=exc)


class CheckInternalTests(TestCase):
    def test_a_plain_answer_is_reachable(self):
        with mock.patch.object(SCRIPT.urllib.request, "urlopen") as opener:
            self.assertIsNone(SCRIPT.check_internal(ONION))
        self.assertEqual(opener.call_args.args[0], f"http://{ONION}/")

    def test_the_probe_carries_a_timeout(self):
        with mock.patch.object(SCRIPT.urllib.request, "urlopen") as opener:
            SCRIPT.check_internal(ONION)
        self.assertEqual(opener.call_args.kwargs["timeout"], 15)

    def test_an_http_error_status_still_counts_as_reached(self):
        error = urllib.error.HTTPError(
            f"http://{ONION}/", 502, "Bad Gateway", hdrs=None, fp=None
        )
        with _urlopen_raising(error):
            self.assertIsNone(SCRIPT.check_internal(ONION))

    def test_a_closed_connection_counts_as_reached(self):
        """OpenResty answering and hanging up proves the fast path resolved."""
        with _urlopen_raising(OSError("closed connection by peer")):
            self.assertIsNone(SCRIPT.check_internal(ONION))

    def test_a_remote_disconnect_counts_as_reached(self):
        with _urlopen_raising(Exception("RemoteDisconnected: no response")):
            self.assertIsNone(SCRIPT.check_internal(ONION))

    def test_a_refused_connection_counts_as_reached(self):
        """The resolver short-circuited to loopback; only the port was shut."""
        with _urlopen_raising(ConnectionRefusedError("Connection refused")):
            self.assertIsNone(SCRIPT.check_internal(ONION))

    def test_a_timeout_is_reported_as_unreachable(self):
        with _urlopen_raising(TimeoutError("timed out")):
            message = SCRIPT.check_internal(ONION)
        self.assertIsNotNone(message)
        self.assertIn("loopback fast path", message)
        self.assertIn("TimeoutError", message)

    def test_an_unresolved_name_is_reported_as_unreachable(self):
        with _urlopen_raising(urllib.error.URLError("Name or service not known")):
            message = SCRIPT.check_internal(ONION)
        self.assertIsNotNone(message)
        self.assertIn("URLError", message)


class MainTests(TestCase):
    def test_a_reachable_onion_exits_quietly(self):
        with mock.patch.object(SCRIPT, "check_internal", return_value=None):
            SCRIPT.main(["onion_self_reach.py", ONION])

    def test_an_unreachable_onion_exits_with_the_reason(self):
        with (
            mock.patch.object(SCRIPT, "check_internal", return_value="boom"),
            self.assertRaises(SystemExit) as raised,
        ):
            SCRIPT.main(["onion_self_reach.py", ONION])
        self.assertEqual(raised.exception.code, "boom")

    def test_a_missing_argument_exits_with_usage(self):
        with self.assertRaises(SystemExit) as raised:
            SCRIPT.main(["onion_self_reach.py"])
        self.assertIn("usage", str(raised.exception.code))


if __name__ == "__main__":
    main()
