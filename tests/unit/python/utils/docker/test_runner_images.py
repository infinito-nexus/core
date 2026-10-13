from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.docker.image.discovery import iter_runner_images

COMPOSE = """\
services:
  coredns:
    image: coredns/coredns:1.14.4
  infinito:
    build:
      context: .
  interpolated:
    image: ${INFINITO_IMAGE}
  untagged:
    image: busybox
  pinned:
    image: nginx@sha256:d5591131b1d898cd02fc7a17adb8ea026352d67809bc9289707778e9e03a76a4
"""

CACHE_OVERRIDE = """\
services:
  package-cache-frontend:
    image: nginx:1.27-alpine
"""

DEFAULT_ENV = "INFINITO_CACHE_PACKAGE_FRONTEND_INIT_IMAGE=alpine:latest\n"


def _repo(root: Path) -> Path:
    (root / "compose").mkdir()
    (root / "compose.yml").write_text(COMPOSE)
    (root / "compose" / "cache.override.yml").write_text(CACHE_OVERRIDE)
    (root / "default.env").write_text(DEFAULT_ENV)
    return root


class TestRunnerImages(unittest.TestCase):
    def test_tagged_literals_and_the_init_image_are_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            found = [
                (image.source_file, image.service, image.source)
                for image in iter_runner_images(_repo(Path(tmp)))
            ]
        self.assertEqual(
            found,
            [
                ("compose.yml", "coredns", "docker.io/coredns/coredns:1.14.4"),
                (
                    "compose/cache.override.yml",
                    "package-cache-frontend",
                    "docker.io/library/nginx:1.27-alpine",
                ),
                (
                    "default.env",
                    "INFINITO_CACHE_PACKAGE_FRONTEND_INIT_IMAGE",
                    "docker.io/library/alpine:latest",
                ),
            ],
        )

    def test_the_repository_declares_coredns_where_the_runner_reads_it(self) -> None:
        services = {
            (image.source_file, image.service)
            for image in iter_runner_images(PROJECT_ROOT)
        }
        self.assertIn(("compose.yml", "coredns"), services)
        self.assertIn(
            ("default.env", "INFINITO_CACHE_PACKAGE_FRONTEND_INIT_IMAGE"), services
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
