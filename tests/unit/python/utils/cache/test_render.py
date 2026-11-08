"""Unit tests for writing the generated package-cache files.

The shape measured in a gate run: a container had rendered
compose/package-cache/pip.conf under its own uid, and the next host-side
render died on it with PermissionError while the directory stayed writable.
"""

from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from utils.cache.hosts import host_records, hosts_serving
from utils.cache.render import _write, apt_list, cache_consumer_yml, upstreams_conf

OLLAMA_HOST = "registry.ollama.ai"
OLLAMA_REPO = "raw-ollama-registry"


class TestWrite(unittest.TestCase):
    """A file the renderer cannot overwrite is replaced, not given up on."""

    def test_an_unwritable_file_is_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory, "pip.conf")
            target.write_text("stale", encoding="utf-8")
            target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

            _write(target, "fresh")

            self.assertEqual(
                target.read_text(
                    encoding="utf-8"
                ),  # nocheck: cache-read tempdir fixture rewritten in this test
                "fresh",
            )

    def test_a_writable_file_keeps_its_inode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory, "arch.list")
            target.write_text("stale", encoding="utf-8")
            before = target.stat().st_ino

            _write(target, "fresh")

            self.assertEqual(
                target.read_text(
                    encoding="utf-8"
                ),  # nocheck: cache-read tempdir fixture rewritten in this test
                "fresh",
            )
            self.assertEqual(target.stat().st_ino, before)

    def test_a_missing_parent_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory, "apt", "debian.list")

            _write(target, "fresh")

            self.assertEqual(
                target.read_text(
                    encoding="utf-8"
                ),  # nocheck: cache-read tempdir fixture rewritten in this test
                "fresh",
            )


class TestOllamaRegistry(unittest.TestCase):
    def test_the_probe_requests_a_path_under_v2(self) -> None:
        self.assertEqual(
            host_records()[OLLAMA_HOST]["routes"],
            [{"path": "/v2/", "repo": OLLAMA_REPO}],
            f"{OLLAMA_HOST} answers 503 on its bare root, so the package-cache "
            "probe must request a path under /v2/, which it serves",
        )

    def test_the_tls_frontend_still_proxies_the_whole_host(self) -> None:
        block = next(
            block
            for block in upstreams_conf().split("server {")
            if f"server_name {OLLAMA_HOST};" in block
        )

        self.assertIn("location / {", block)
        self.assertIn(f"/repository/{OLLAMA_REPO}/;", block)
        self.assertNotIn("location /v2/", block)


class TestServedByThePin(unittest.TestCase):
    def setUp(self) -> None:
        self.own = host_records()
        self.apt = hosts_serving("apt-debian")[0].host
        self.changed = OLLAMA_HOST
        self.kept = next(
            name for name in self.own if name not in (self.apt, self.changed)
        )

    def _served(self) -> dict:
        served = {
            name: dict(record) for name, record in self.own.items() if name != self.apt
        }
        served[self.changed]["read_timeout"] = "changed"
        return served

    def test_a_host_the_pin_lacks_or_declares_differently_is_not_hijacked(
        self,
    ) -> None:
        rendered = cache_consumer_yml(self._served())
        self.assertNotIn(f'"{self.apt}:', rendered)
        self.assertNotIn(f'"{self.changed}:', rendered)
        self.assertIn(f'"{self.kept}:', rendered)
        self.assertIn(f'"{self.apt}:', cache_consumer_yml())
        self.assertEqual(cache_consumer_yml(), cache_consumer_yml(self.own))

    def test_an_unreadable_pin_hijacks_no_host(self) -> None:
        rendered = cache_consumer_yml({})
        self.assertNotIn(":${INFINITO_CACHE_PACKAGE_FRONTEND_IP}", rendered)
        self.assertIn("infinito-registry-cache:", rendered)

    def test_an_apt_host_the_pin_does_not_serve_leaves_the_base_sources(self) -> None:
        self.assertIn(self.apt, apt_list("debian"))
        self.assertNotIn("deb ", apt_list("debian", self._served()))


if __name__ == "__main__":
    unittest.main()
