from __future__ import annotations

import io
import unittest
import unittest.mock as mock
import urllib.error

from tests.utils.redirecting_site import REDIRECT_TARGET, redirecting_site

from ._fake_monitoring import WS, RunError, cmk, rest


class TestTheCheckmkClient(unittest.TestCase):
    def test_an_answer_echoing_the_request_never_carries_the_secret(self) -> None:
        secret = "s3cr3t-of-the-automation-user"
        for echoed in (b'{"detail": "denied %s"}', b"denied %s"):

            def refuse(request, timeout, echoed=echoed):
                body = echoed % request.get_header("Authorization").encode()
                raise urllib.error.HTTPError(
                    request.full_url, 401, "Unauthorized", {}, io.BytesIO(body)
                )

            opener = mock.Mock(open=refuse)
            with self.subTest(echoed=echoed):
                with (
                    mock.patch.object(rest.ssl, "create_default_context"),
                    mock.patch.object(
                        rest.urllib.request, "build_opener", return_value=opener
                    ),
                ):
                    call = rest.rest_api(
                        "https://site.example/check_mk/api/1.0",
                        "automation",
                        secret,
                        "/nonexistent",
                    )
                    site = cmk.Checkmk(call, "site", lambda _: None, "automation")
                    with self.assertRaises(RunError) as raised:
                        site.hosts(WS)
                self.assertIn("<secret>", str(raised.exception))
                self.assertNotIn(secret, str(raised.exception))

    def test_a_redirect_is_an_answer_and_the_secret_never_follows_it(self) -> None:
        secret = "s3cr3t-of-the-automation-user"
        with (
            redirecting_site() as (base, seen),
            mock.patch.object(rest.ssl, "create_default_context"),
        ):
            call = rest.rest_api(base, "automation", secret, "/nonexistent")
            site = cmk.Checkmk(call, "site", lambda _: None, "automation")
            with self.assertRaisesRegex(RunError, "answered 302"):
                site.hosts(WS)
        self.assertEqual(len(seen), 1)
        self.assertNotIn(REDIRECT_TARGET, [path for path, _ in seen])


if __name__ == "__main__":
    unittest.main()
