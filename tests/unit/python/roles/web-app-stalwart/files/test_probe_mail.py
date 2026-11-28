"""The mail probe must ride out a Stalwart restart, not fail on its first refusal.

The deploy restarts Stalwart for its OIDC and certificate settings right before
the CLI test, and /healthz/ready answers before the SMTP listeners are bound
again: Snipe-IT#0 failed its relay check on one ConnectionRefusedError.
"""

import importlib.util
import sys
import unittest
import unittest.mock as mock

from . import PROJECT_ROOT


def _load_module():
    path = PROJECT_ROOT / "roles/web-app-stalwart/files/test/probe/mail.py"
    spec = importlib.util.spec_from_file_location("probe_mail", str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["probe_mail"] = mod
    spec.loader.exec_module(mod)
    return mod


_M = _load_module()


class TestConnect(unittest.TestCase):
    def test_a_refused_connect_is_retried_until_it_opens(self):
        session = object()
        opener = mock.Mock(side_effect=[ConnectionRefusedError, session])
        with mock.patch.object(_M.time, "sleep"):
            self.assertIs(_M.connect(opener), session)
        self.assertEqual(opener.call_count, 2)

    def test_a_listener_that_stays_down_fails_after_the_timeout(self):
        opener = mock.Mock(side_effect=ConnectionRefusedError)
        clock = iter([0, 0, _M.TIMEOUT + 1])
        with (
            mock.patch.object(_M.time, "monotonic", side_effect=lambda: next(clock)),
            mock.patch.object(_M.time, "sleep"),
            self.assertRaises(ConnectionRefusedError),
        ):
            _M.connect(opener)

    def test_other_errors_are_not_retried(self):
        opener = mock.Mock(side_effect=TimeoutError)
        with self.assertRaises(TimeoutError):
            _M.connect(opener)
        self.assertEqual(opener.call_count, 1)


if __name__ == "__main__":
    unittest.main()
