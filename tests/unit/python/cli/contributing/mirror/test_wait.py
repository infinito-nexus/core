from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import patch

import cli.contributing.mirror.wait.__main__ as wait_main
from utils.docker.image.discovery import ImageRef

from . import NODE, NODE_MIRROR

COREDNS = ImageRef(
    role="runner",
    service="coredns",
    name="coredns/coredns",
    version="1.14.4",
    source="docker.io/coredns/coredns:1.14.4",
    registry="docker.io",
    source_file="compose.yml",
)


class TestMirrorWait(unittest.TestCase):
    def test_missing_refs_name_the_tag_and_the_digest_reference(self) -> None:
        stderr = io.StringIO()
        with (
            patch(
                "cli.contributing.mirror.wait.__main__.iter_role_images",
                return_value=[NODE],
            ),
            patch(
                "cli.contributing.mirror.wait.__main__.iter_runner_images",
                return_value=[COREDNS],
            ),
            patch.object(wait_main.GHCRProvider, "tag_exists", return_value=False),
            patch(
                "sys.argv",
                [
                    "mirror-wait",
                    "--ghcr-namespace",
                    "acme",
                    "--ghcr-repository",
                    "myrepo",
                    "--attempts",
                    "1",
                    "--sleep-seconds",
                    "1",
                ],
            ),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(stderr),
        ):
            result = wait_main.main()

        self.assertEqual(result, 1)
        self.assertEqual(
            [line for line in stderr.getvalue().splitlines() if line.startswith(" - ")],
            [
                f" - {NODE_MIRROR}",
                " - ghcr.io/acme/myrepo/mirror/docker.io/coredns/coredns:1.14.4",
            ],
        )

    def test_a_missing_runner_mirror_keeps_the_wait_open(self) -> None:
        image = COREDNS

        with (
            patch(
                "cli.contributing.mirror.wait.__main__.iter_role_images",
                return_value=[],
            ),
            patch(
                "cli.contributing.mirror.wait.__main__.iter_runner_images",
                return_value=[image],
            ),
            patch.object(
                wait_main.GHCRProvider, "tag_exists", return_value=False
            ) as tag_exists,
            patch(
                "sys.argv",
                [
                    "mirror-wait",
                    "--ghcr-namespace",
                    "acme",
                    "--ghcr-repository",
                    "myrepo",
                    "--attempts",
                    "1",
                    "--sleep-seconds",
                    "1",
                ],
            ),
        ):
            result = wait_main.main()

        self.assertEqual(result, 1)
        tag_exists.assert_called_once_with(image)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
