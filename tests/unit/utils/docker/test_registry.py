from __future__ import annotations

import io
import unittest
import urllib.error
from email.message import Message
from unittest import mock

from utils.docker import registry


def _headers(values: dict[str, str] | None = None) -> Message:
    msg = Message()
    for key, value in (values or {}).items():
        msg[key] = value
    return msg


class _Resp:
    def __init__(self, status: int = 200, headers=None, body: bytes = b""):
        self.status = status
        self.headers = _headers(headers)
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> bool:
        return False


def _http_error(code: int, headers=None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://reg/v2", code, "err", _headers(headers), io.BytesIO(b"")
    )


class TestManifestExists(unittest.TestCase):
    def test_present_returns_true(self) -> None:
        with mock.patch.object(
            registry.urllib.request, "urlopen", return_value=_Resp(status=200)
        ) as opened:
            self.assertIs(registry.manifest_exists("postgres", "16"), True)
        url = opened.call_args.args[0].full_url
        self.assertEqual(
            url, "https://registry-1.docker.io/v2/library/postgres/manifests/16"
        )

    def test_absent_returns_false(self) -> None:
        with mock.patch.object(
            registry.urllib.request, "urlopen", side_effect=_http_error(404)
        ):
            self.assertIs(registry.manifest_exists("postgres", "999"), False)

    def test_network_error_is_indeterminate(self) -> None:
        with mock.patch.object(
            registry.urllib.request, "urlopen", side_effect=urllib.error.URLError("x")
        ):
            self.assertIsNone(registry.manifest_exists("postgres", "16"))

    def test_auth_wall_without_realm_is_indeterminate(self) -> None:
        with mock.patch.object(
            registry.urllib.request, "urlopen", side_effect=_http_error(401)
        ):
            self.assertIsNone(registry.manifest_exists("quay.io/foo/bar", "1"))

    def test_non_dockerhub_registry_host(self) -> None:
        with mock.patch.object(
            registry.urllib.request, "urlopen", return_value=_Resp(status=200)
        ) as opened:
            registry.manifest_exists("quay.io/keycloak/keycloak", "26.6.3")
        url = opened.call_args.args[0].full_url
        self.assertEqual(url, "https://quay.io/v2/keycloak/keycloak/manifests/26.6.3")


class TestFetchRegistryTags(unittest.TestCase):
    def test_anonymous_tags(self) -> None:
        with mock.patch.object(
            registry.urllib.request,
            "urlopen",
            return_value=_Resp(body=b'{"tags": ["1.0.0", "1.1.0"]}'),
        ):
            self.assertEqual(
                registry.fetch_registry_tags("mcr.microsoft.com/foo/bar"),
                ["1.0.0", "1.1.0"],
            )

    def test_bearer_challenge_then_retry(self) -> None:
        challenge = 'Bearer realm="https://auth.example/token",service="reg",scope="repository:foo/bar:pull"'

        def _fake(req, *_a, **_kw):
            url = req.full_url
            if url.startswith("https://auth.example/token"):
                return _Resp(body=b'{"token": "abc"}')
            if "Authorization" not in req.headers and "Authorization" not in {
                k.title(): v for k, v in req.header_items()
            }:
                raise _http_error(401, {"WWW-Authenticate": challenge})
            return _Resp(body=b'{"tags": ["2.0.0"]}')

        with mock.patch.object(registry.urllib.request, "urlopen", side_effect=_fake):
            self.assertEqual(registry.fetch_registry_tags("ghcr.io/foo/bar"), ["2.0.0"])

    def test_pagination_follows_link(self) -> None:
        page1 = _Resp(
            headers={"Link": '</v2/library/foo/tags/list?n=100&last=b>; rel="next"'},
            body=b'{"tags": ["a"]}',
        )
        page2 = _Resp(body=b'{"tags": ["b"]}')
        with mock.patch.object(
            registry.urllib.request, "urlopen", side_effect=[page1, page2]
        ):
            self.assertEqual(registry.fetch_registry_tags("foo"), ["a", "b"])

    def test_network_failure_returns_empty(self) -> None:
        with mock.patch.object(
            registry.urllib.request, "urlopen", side_effect=urllib.error.URLError("x")
        ):
            self.assertEqual(registry.fetch_registry_tags("foo"), [])

    def test_last_cursor_seeds_query(self) -> None:
        with mock.patch.object(
            registry.urllib.request,
            "urlopen",
            return_value=_Resp(body=b'{"tags": ["v1.0.0"]}'),
        ) as opened:
            self.assertEqual(
                registry.fetch_registry_tags("registry.gitlab.com/foo/bar", last="v"),
                ["v1.0.0"],
            )
        url = opened.call_args.args[0].full_url
        self.assertEqual(
            url, "https://registry.gitlab.com/v2/foo/bar/tags/list?n=1000&last=v"
        )


if __name__ == "__main__":
    unittest.main()
