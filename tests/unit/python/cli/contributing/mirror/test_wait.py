from __future__ import annotations

import unittest
from unittest.mock import patch

import cli.contributing.mirror.wait.__main__ as wait_main
from cli.contributing.mirror.model import ImageRef


class TestMirrorWait(unittest.TestCase):
    def test_a_missing_runner_mirror_keeps_the_wait_open(self) -> None:
        image = ImageRef(
            role="runner",
            service="coredns",
            name="coredns/coredns",
            version="1.14.4",
            source="docker.io/coredns/coredns:1.14.4",
            registry="docker.io",
            source_file="compose.yml",
        )

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
