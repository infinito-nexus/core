from __future__ import annotations

import unittest
import urllib.error
import urllib.request

from infinito_elector_src.server import serve

from . import _NAME  # noqa: F401  side-effect import registers infinito_elector_src


class TestWriterEndpoint(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {"writer": False}
        self.server = serve(lambda: self.state["writer"], "127.0.0.1", 0)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _status(self, path: str) -> int:
        try:
            with urllib.request.urlopen(self.base + path, timeout=2) as response:  # noqa: S310 - fixed http URL to the local test server
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def test_503_while_not_writer(self) -> None:
        self.assertEqual(self._status("/writer"), 503)

    def test_200_while_writer(self) -> None:
        self.state["writer"] = True
        self.assertEqual(self._status("/writer"), 200)

    def test_unknown_path_is_404(self) -> None:
        self.assertEqual(self._status("/"), 404)

    def test_seed_is_404_without_a_donor(self) -> None:
        request = urllib.request.Request(self.base + "/seed", data=b"{}", method="POST")  # noqa: S310 - local test server
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=2)  # noqa: S310 - local test server
        self.assertEqual(caught.exception.code, 404)


class TestSeedEndpoint(unittest.TestCase):
    def test_post_seed_answers_the_donor_status(self) -> None:
        bodies: list[tuple[bytes, str]] = []

        def seed(body: bytes, peer: str) -> int:
            bodies.append((body, peer))
            return 202

        server = serve(lambda: False, "127.0.0.1", 0, seed)
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/seed"
            request = urllib.request.Request(url, data=b'{"host": "m3"}', method="POST")
            with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310 - local test server
                self.assertEqual(response.status, 202)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(bodies, [(b'{"host": "m3"}', "127.0.0.1")])


if __name__ == "__main__":
    unittest.main()
