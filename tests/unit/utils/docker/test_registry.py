from __future__ import annotations

import io
import os
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

from utils.docker import registry


class _IsolatedProbeCache(unittest.TestCase):
    """Give each test its own probe cache and no mirror."""

    def setUp(self) -> None:
        super().setUp()
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        for patcher in (
            mock.patch.object(registry, "_CACHE_ROOT", Path(cache.name)),
            mock.patch.dict(os.environ, {"INFINITO_GHCR_MIRROR_PREFIX": ""}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)


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


class TestManifestExists(_IsolatedProbeCache):
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


_SINGLE = {
    "config": {"size": 100},
    "layers": [{"size": 900}, {"size": 1_000}],
}
_INDEX = {
    "manifests": [
        {"digest": "sha256:arm", "platform": {"os": "linux", "architecture": "arm64"}},
        {"digest": "sha256:amd", "platform": {"os": "linux", "architecture": "amd64"}},
        {
            "digest": "sha256:att",
            "platform": {"os": "unknown", "architecture": "unknown"},
        },
    ]
}


class TestManifestTransferSize(_IsolatedProbeCache):
    def test_single_manifest_sums_config_and_layers(self) -> None:
        with mock.patch.object(registry, "fetch_manifest", return_value=_SINGLE):
            self.assertEqual(registry.manifest_transfer_size("img", "1"), 2_000)

    def test_index_resolves_the_requested_platform(self) -> None:
        with mock.patch.object(
            registry, "fetch_manifest", side_effect=[_INDEX, _SINGLE]
        ) as fetched:
            self.assertEqual(registry.manifest_transfer_size("img", "1"), 2_000)
        self.assertEqual(fetched.call_args_list[1].args, ("img", "sha256:amd"))

    def test_index_without_the_platform_is_indeterminate(self) -> None:
        with mock.patch.object(registry, "fetch_manifest", return_value=_INDEX):
            self.assertIsNone(
                registry.manifest_transfer_size("img", "1", architecture="riscv64")
            )

    def test_missing_config_size_counts_layers_only(self) -> None:
        with mock.patch.object(
            registry, "fetch_manifest", return_value={"layers": [{"size": 7}]}
        ):
            self.assertEqual(registry.manifest_transfer_size("img", "1"), 7)

    def test_layerless_manifest_is_indeterminate(self) -> None:
        with mock.patch.object(registry, "fetch_manifest", return_value={"config": {}}):
            self.assertIsNone(registry.manifest_transfer_size("img", "1"))

    def test_a_measured_size_is_served_from_cache(self) -> None:
        with mock.patch.object(registry, "fetch_manifest", return_value=_SINGLE):
            self.assertEqual(registry.manifest_transfer_size("img", "1"), 2_000)
        with mock.patch.object(registry, "fetch_manifest") as fetched:
            self.assertEqual(registry.manifest_transfer_size("img", "1"), 2_000)
        fetched.assert_not_called()

    def test_an_indeterminate_answer_is_not_cached(self) -> None:
        with mock.patch.object(registry, "fetch_manifest", return_value=None):
            self.assertIsNone(registry.manifest_transfer_size("img", "1"))
        with mock.patch.object(registry, "fetch_manifest", return_value=_SINGLE):
            self.assertEqual(registry.manifest_transfer_size("img", "1"), 2_000)

    def test_platform_is_part_of_the_cache_key(self) -> None:
        with mock.patch.object(registry, "fetch_manifest", return_value=_SINGLE):
            self.assertEqual(registry.manifest_transfer_size("img", "1"), 2_000)
        with mock.patch.object(
            registry, "fetch_manifest", return_value={"layers": [{"size": 9}]}
        ):
            self.assertEqual(
                registry.manifest_transfer_size("img", "1", architecture="arm64"), 9
            )


class TestProbeOrder(_IsolatedProbeCache):
    def test_the_mirror_is_probed_before_the_upstream_registry(self) -> None:
        with mock.patch.dict(os.environ, {"INFINITO_GHCR_MIRROR_PREFIX": "mirror"}):
            order = registry._probe_order("postgres")
        self.assertEqual(len(order), 2)
        self.assertTrue(order[0].startswith("ghcr.io/"))
        self.assertTrue(order[0].endswith("/mirror/docker.io/postgres"))
        self.assertEqual(order[1], "postgres")

    def test_upstream_is_the_only_probe_without_a_mirror(self) -> None:
        self.assertEqual(registry._probe_order("postgres"), ["postgres"])

    def test_upstream_answers_when_the_mirror_lacks_the_image(self) -> None:
        with (
            mock.patch.dict(os.environ, {"INFINITO_GHCR_MIRROR_PREFIX": "mirror"}),
            mock.patch.object(
                registry, "fetch_manifest", side_effect=[None, _SINGLE]
            ) as fetched,
        ):
            self.assertEqual(registry.manifest_transfer_size("postgres", "17"), 2_000)
        self.assertEqual(fetched.call_args_list[1].args[0], "postgres")

    def test_unreachable_manifest_is_indeterminate(self) -> None:
        with mock.patch.object(registry, "fetch_manifest", return_value=None):
            self.assertIsNone(registry.manifest_transfer_size("img", "1"))

    def test_nested_index_is_indeterminate(self) -> None:
        with mock.patch.object(
            registry, "fetch_manifest", side_effect=[_INDEX, _INDEX]
        ):
            self.assertIsNone(registry.manifest_transfer_size("img", "1"))


class TestFetchManifest(unittest.TestCase):
    def test_non_dict_body_is_indeterminate(self) -> None:
        with mock.patch.object(
            registry.urllib.request, "urlopen", return_value=_Resp(body=b"[]")
        ):
            self.assertIsNone(registry.fetch_manifest("img", "1"))

    def test_rate_limited_is_indeterminate(self) -> None:
        with mock.patch.object(
            registry.urllib.request, "urlopen", side_effect=_http_error(429)
        ):
            self.assertIsNone(registry.fetch_manifest("img", "1"))

    def test_present_manifest_is_parsed(self) -> None:
        with mock.patch.object(
            registry.urllib.request,
            "urlopen",
            return_value=_Resp(body=b'{"layers": []}'),
        ):
            self.assertEqual(registry.fetch_manifest("img", "1"), {"layers": []})


if __name__ == "__main__":
    unittest.main()
