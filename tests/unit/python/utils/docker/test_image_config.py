"""A config-blob read must separate "declares none" from "could not tell".

A sweep that reads an indeterminate answer as an absent probe reports every
image as a gap the moment the network hiccups.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.docker import registry
from utils.docker.image import config

MANIFEST = {"config": {"digest": "sha256:cfg"}, "layers": [{"size": 1}]}
INDEX = {
    "manifests": [
        {"platform": {"os": "linux", "architecture": "amd64"}, "digest": "sha256:amd"}
    ]
}
PROBE = {"Test": ["CMD-SHELL", "dig @127.0.0.1 || exit 1"]}
VOLUMES = {"/opt/ejabberd": {}}


class _Isolated:
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

    def serve(self, manifest, blob):
        """Answer manifest requests with *manifest* and blob requests with *blob*."""

        def _request(url, repo, method, accept):
            if "/blobs/" in url:
                return (200, {}, json.dumps(blob).encode()) if blob else None
            return (200, {}, json.dumps(manifest).encode()) if manifest else None

        return mock.patch.object(registry, "_request", side_effect=_request)


class TestImageHealthcheck(_Isolated, unittest.TestCase):
    def test_a_declared_probe_comes_back(self) -> None:
        with self.serve(MANIFEST, {"config": {"Healthcheck": PROBE}}):
            self.assertEqual(config.image_healthcheck("redis", "alpine"), PROBE)

    def test_an_image_without_one_answers_with_an_empty_mapping(self) -> None:
        with self.serve(MANIFEST, {"config": {}}):
            self.assertEqual(config.image_healthcheck("redis", "alpine"), {})

    def test_an_unreachable_registry_is_indeterminate_not_absent(self) -> None:
        with mock.patch.object(registry, "_request", return_value=None):
            self.assertIsNone(config.image_healthcheck("redis", "alpine"))

    def test_a_multi_platform_index_is_resolved_to_the_platform(self) -> None:
        seen = []

        def _request(url, repo, method, accept):
            seen.append(url)
            if "/blobs/" in url:
                return (
                    200,
                    {},
                    json.dumps({"config": {"Healthcheck": PROBE}}).encode(),
                )
            body = MANIFEST if "sha256%3Aamd" in url else INDEX
            return (200, {}, json.dumps(body).encode())

        with mock.patch.object(registry, "_request", side_effect=_request):
            self.assertEqual(config.image_healthcheck("redis", "alpine"), PROBE)
        self.assertTrue(any("sha256%3Aamd" in url for url in seen))

    def test_an_index_without_the_platform_is_indeterminate(self) -> None:
        with (
            self.serve(INDEX, {"config": {}}),
            mock.patch.object(config, "platform_digest", return_value=None),
        ):
            self.assertIsNone(config.image_healthcheck("redis", "alpine"))

    def test_a_determinate_answer_is_cached(self) -> None:
        calls = []

        def _request(url, repo, method, accept):
            calls.append(url)
            if "/blobs/" in url:
                return (200, {}, json.dumps({"config": {}}).encode())
            return (200, {}, json.dumps(MANIFEST).encode())

        with mock.patch.object(registry, "_request", side_effect=_request):
            config.image_healthcheck("redis", "alpine")
            before = len(calls)
            config.image_healthcheck("redis", "alpine")
        self.assertEqual(len(calls), before, "the second read must come from cache")


class TestImageVolumes(_Isolated, unittest.TestCase):
    def test_declared_paths_come_back(self) -> None:
        with self.serve(MANIFEST, {"config": {"Volumes": VOLUMES}}):
            self.assertEqual(config.image_volumes("ejabberd", "26.09"), VOLUMES)

    def test_an_image_without_any_answers_with_an_empty_mapping(self) -> None:
        with self.serve(MANIFEST, {"config": {}}):
            self.assertEqual(config.image_volumes("ejabberd", "26.09"), {})

    def test_an_unreachable_registry_is_indeterminate_not_absent(self) -> None:
        with mock.patch.object(registry, "_request", return_value=None):
            self.assertIsNone(config.image_volumes("ejabberd", "26.09"))

    def test_the_two_sections_do_not_share_a_cache_entry(self) -> None:
        with self.serve(MANIFEST, {"config": {"Volumes": VOLUMES}}):
            self.assertEqual(config.image_volumes("ejabberd", "26.09"), VOLUMES)
            self.assertEqual(config.image_healthcheck("ejabberd", "26.09"), {})


class TestProbeSource(_Isolated, unittest.TestCase):
    def test_the_source_says_where_the_answer_came_from(self) -> None:
        with self.serve(MANIFEST, {"config": {}}):
            _found, source = config.image_healthcheck_probed("redis", "alpine")
        self.assertEqual(source, "upstream")

    def test_a_cached_answer_says_so(self) -> None:
        with self.serve(MANIFEST, {"config": {}}):
            config.image_healthcheck_probed("redis", "alpine")
            _found, source = config.image_healthcheck_probed("redis", "alpine")
        self.assertEqual(source, "cache")

    def test_an_unreachable_registry_reports_none(self) -> None:
        with mock.patch.object(registry, "_request", return_value=None):
            found, source = config.image_healthcheck_probed("redis", "alpine")
        self.assertIsNone(found)
        self.assertEqual(source, "none")


if __name__ == "__main__":
    unittest.main()
