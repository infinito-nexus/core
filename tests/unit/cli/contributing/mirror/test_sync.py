from __future__ import annotations

import unittest
from unittest.mock import patch

import cli.contributing.mirror.sync.__main__ as sync_main
from cli.contributing.mirror.model import ImageRef


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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
