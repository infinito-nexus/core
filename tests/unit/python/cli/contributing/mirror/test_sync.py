from __future__ import annotations

import unittest
from unittest.mock import patch

import cli.contributing.mirror.sync.__main__ as sync_main
from cli.contributing.mirror.model import ImageRef


class TestThrottle(unittest.TestCase):
    def test_only_docker_hub_copies_wait_for_the_throttle(self) -> None:
        def image(name: str, registry: str) -> ImageRef:
            return ImageRef(
                role="r",
                service=name,
                name=name,
                version="1",
                source=f"{registry}/{name}:1",
                registry=registry,
            )

        images = [
            image("a", "docker.io"),
            image("b", "ghcr.io"),
            image("c", "quay.io"),
            image("d", "docker.io"),
        ]
        with (
            patch(
                "cli.contributing.mirror.sync.__main__.iter_role_images",
                return_value=images,
            ),
            patch(
                "cli.contributing.mirror.sync.__main__.iter_runner_images",
                return_value=[],
            ),
            patch.object(sync_main.GHCRProvider, "image_base", return_value="g/x"),
            patch.object(sync_main.GHCRProvider, "mirror") as mock_mirror,
            patch.object(sync_main.time, "monotonic", return_value=0.0),
            patch.object(sync_main.time, "sleep") as mock_sleep,
            patch(
                "sys.argv",
                [
                    "mirror-sync",
                    "--ghcr-namespace",
                    "acme",
                    "--ghcr-repository",
                    "myrepo",
                    "--images-per-hour",
                    "150",
                ],
            ),
        ):
            result = sync_main.main()

        self.assertEqual(result, 0)
        self.assertEqual(mock_mirror.call_count, 4)
        self.assertEqual([call.args for call in mock_sleep.call_args_list], [(24.0,)])


class TestMirrorSync(unittest.TestCase):
    def test_only_missing_skips_existing_destination(self) -> None:
        image = ImageRef(
            role="web-app-nextcloud",
            service="app",
            name="nextcloud",
            version="31.0.0",
            source="docker.io/library/nextcloud:31.0.0",
            registry="docker.io",
        )

        with (
            patch(
                "cli.contributing.mirror.sync.__main__.iter_role_images",
                return_value=[image],
            ),
            patch(
                "cli.contributing.mirror.sync.__main__.iter_runner_images",
                return_value=[],
            ),
            patch.object(
                sync_main.GHCRProvider,
                "image_base",
                return_value="ghcr.io/acme/myrepo/mirror/docker.io/nextcloud",
            ),
            patch.object(
                sync_main.GHCRProvider, "tag_exists", return_value=True
            ) as mock_tag_exists,
            patch.object(sync_main.GHCRProvider, "mirror") as mock_mirror,
            patch(
                "sys.argv",
                [
                    "mirror-sync",
                    "--ghcr-namespace",
                    "acme",
                    "--ghcr-repository",
                    "myrepo",
                    "--only-missing",
                ],
            ),
        ):
            result = sync_main.main()

        self.assertEqual(result, 0)
        mock_tag_exists.assert_called_once_with(image)
        mock_mirror.assert_not_called()

    def test_runner_images_are_mirrored_with_the_role_images(self) -> None:
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
                "cli.contributing.mirror.sync.__main__.iter_role_images",
                return_value=[],
            ),
            patch(
                "cli.contributing.mirror.sync.__main__.iter_runner_images",
                return_value=[image],
            ),
            patch.object(sync_main.GHCRProvider, "mirror") as mock_mirror,
            patch(
                "sys.argv",
                [
                    "mirror-sync",
                    "--ghcr-namespace",
                    "acme",
                    "--ghcr-repository",
                    "myrepo",
                ],
            ),
        ):
            result = sync_main.main()

        self.assertEqual(result, 0)
        mock_mirror.assert_called_once_with(image)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
