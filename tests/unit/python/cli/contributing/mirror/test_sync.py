from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

import cli.contributing.mirror.sync.__main__ as sync_main
from cli.contributing.mirror.model import ImageRef


class TestMirrorSync(unittest.TestCase):
    IMAGE = ImageRef(
        role="web-app-nextcloud",
        service="app",
        name="nextcloud",
        version="31.0.0",
        source="docker.io/library/nextcloud:31.0.0",
        registry="docker.io",
    )

    def _run_only_missing(self, *, stale: bool, mirror_error=None):
        with (
            patch(
                "cli.contributing.mirror.sync.__main__.iter_role_images",
                return_value=[self.IMAGE],
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
            patch.object(
                sync_main.GHCRProvider, "is_stale", return_value=stale
            ) as mock_is_stale,
            patch.object(
                sync_main.GHCRProvider, "mirror", side_effect=mirror_error
            ) as mock_mirror,
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
        mock_tag_exists.assert_called_once_with(self.IMAGE)
        mock_is_stale.assert_called_once_with(self.IMAGE)
        return result, mock_mirror

    def test_only_missing_skips_current_destination(self) -> None:
        result, mock_mirror = self._run_only_missing(stale=False)

        self.assertEqual(result, 0)
        mock_mirror.assert_not_called()

    def test_only_missing_refreshes_a_stale_destination(self) -> None:
        result, mock_mirror = self._run_only_missing(stale=True)

        self.assertEqual(result, 0)
        mock_mirror.assert_called_once_with(self.IMAGE)

    def test_failed_refresh_keeps_the_existing_copy_without_failing(self) -> None:
        error = subprocess.CalledProcessError(1, ["skopeo", "copy"])

        result, mock_mirror = self._run_only_missing(stale=True, mirror_error=error)

        self.assertEqual(result, 0)
        mock_mirror.assert_called_once_with(self.IMAGE)

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
