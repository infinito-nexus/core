from __future__ import annotations

import io
import socket
import unittest
import unittest.mock as mock
from contextlib import redirect_stderr
from importlib.util import module_from_spec, spec_from_file_location

from ._semaphore_fake import PYTHON_DIR

PROXY = "egress-proxy:3128"
IPV6 = "2001:db8::10"


def load_egress():
    """Returns:
    The module ``files/python/egress_connect.py``.
    """
    spec = spec_from_file_location(
        "semaphore_egress_connect", str(PYTHON_DIR / "egress_connect.py")
    )
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class EgressConnectTests(unittest.TestCase):
    def setUp(self):
        self.egress = load_egress()
        self.tunnel, self.proxy = socket.socketpair()
        self.addCleanup(self.tunnel.close)
        self.addCleanup(self.proxy.close)
        self.dialed = []

        def dial(address):
            self.dialed.append(address)
            return self.tunnel

        patched = mock.patch.object(self.egress.socket, "create_connection", dial)
        patched.start()
        self.addCleanup(patched.stop)

    def request(self):
        """Returns:
        What the script sent the proxy before its answer was read.
        """
        self.proxy.setblocking(False)
        return self.proxy.recv(4096).decode()

    def test_an_answered_connect_hands_back_the_tunnel(self):
        self.proxy.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        tunnel = self.egress.connect(PROXY, IPV6, "22")
        self.assertIs(tunnel, self.tunnel)
        self.assertEqual(self.dialed, [("egress-proxy", 3128)])
        self.assertEqual(
            self.request(),
            f"CONNECT [{IPV6}]:22 HTTP/1.1\r\nHost: [{IPV6}]:22\r\n\r\n",
        )

    def test_negative_control_a_refused_connect_opens_no_tunnel(self):
        self.proxy.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
        with self.assertRaisesRegex(OSError, "refused 203.0.113.10:22"):
            self.egress.connect(PROXY, "203.0.113.10", "22")

    def test_a_proxy_that_hangs_up_opens_no_tunnel(self):
        self.proxy.sendall(b"HTTP/1.1 200")
        self.proxy.shutdown(socket.SHUT_WR)
        with self.assertRaisesRegex(OSError, "closed the tunnel"):
            self.egress.connect(PROXY, "203.0.113.10", "22")

    def test_main_refuses_a_missing_proxy_or_target(self):
        for argv, environ, code, message in (
            (["203.0.113.10"], {"EGRESS_PROXY": PROXY}, 2, "expects <host> <port>"),
            (["203.0.113.10", "22"], {}, 1, "EGRESS_PROXY"),
        ):
            with self.subTest(argv=argv, environ=environ):
                err = io.StringIO()
                with (
                    mock.patch.dict(self.egress.os.environ, environ, clear=True),
                    redirect_stderr(err),
                ):
                    self.assertEqual(self.egress.main(argv), code)
                self.assertIn(message, err.getvalue())
                self.assertEqual(self.dialed, [])


if __name__ == "__main__":
    unittest.main()
