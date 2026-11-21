from __future__ import annotations

import io
import unittest
import unittest.mock as mock
import urllib.error
from email.message import Message

from utils.update import upstream as module


class TestRegistryV2Tags(unittest.TestCase):
    def test_a_realm_other_than_https_is_never_read(self) -> None:
        for realm in ("file:///tmp/token.json", "http://169.254.169.254/token"):
            headers = Message()
            headers["WWW-Authenticate"] = f'Bearer realm="{realm}",service="reg"'
            denied = urllib.error.HTTPError(
                "https://reg.example/v2", 401, "err", headers, io.BytesIO(b"")
            )
            with (
                self.subTest(realm=realm),
                mock.patch.object(module, "get", side_effect=denied) as get,
            ):
                self.assertEqual(module.registry_v2_tags("reg.example/foo/bar"), [])
                self.assertEqual(
                    [call.args[0] for call in get.call_args_list],
                    ["https://reg.example/v2/foo/bar/tags/list"],
                )

    def test_a_challenge_is_answered_with_the_token_of_its_https_realm(self) -> None:
        headers = Message()
        headers["WWW-Authenticate"] = (
            'Bearer realm="https://auth.example/token",service="reg"'
        )
        denied = urllib.error.HTTPError(
            "https://reg.example/v2", 401, "err", headers, io.BytesIO(b"")
        )
        answers = [denied, '{"token": "t0k"}', '{"tags": ["1.0.0", "1.1.0"]}']

        def get(url, headers=None):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        with mock.patch.object(module, "get", side_effect=get) as fetched:
            self.assertEqual(
                module.registry_v2_tags("reg.example/foo/bar"), ["1.0.0", "1.1.0"]
            )
        self.assertEqual(
            [call.args for call in fetched.call_args_list],
            [
                ("https://reg.example/v2/foo/bar/tags/list",),
                ("https://auth.example/token?service=reg",),
                (
                    "https://reg.example/v2/foo/bar/tags/list",
                    {"Authorization": "Bearer t0k"},
                ),
            ],
        )


class TestNpmVersions(unittest.TestCase):
    def test_every_published_version_is_listed(self) -> None:
        with mock.patch.object(
            module, "get", return_value='{"versions": {"1.0.0": {}, "2.0.0": {}}}'
        ):
            self.assertEqual(module.npm_versions("example"), ["1.0.0", "2.0.0"])

    def test_an_unreachable_registry_lists_nothing(self) -> None:
        with mock.patch.object(module, "get", side_effect=OSError("down")):
            self.assertEqual(module.npm_versions("example"), [])


if __name__ == "__main__":
    unittest.main()
