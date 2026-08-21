from __future__ import annotations

import unittest

from utils.docker.image.ref import is_valid_image_name, split_registry_and_name


class TestDockerImageRef(unittest.TestCase):
    def test_is_valid_image_name_accepts_supported_references(self) -> None:
        valid_images = (
            "nginx",
            "gitea/gitea",
            "docker.io/library/nginx",
            "ghcr.io/acme/example-app",
            "registry.example:5000/team/service",
            "localhost/dev/app",
        )

        for image in valid_images:
            with self.subTest(image=image):
                self.assertTrue(is_valid_image_name(image))

    def test_is_valid_image_name_rejects_invalid_references(self) -> None:
        invalid_images = (
            None,
            "",
            "   ",
            "bad name",
            "nginx:latest",
            "repo@sha256:deadbeef",
            "docker.io/library/nginx:latest",
            "registry.example:5000/team/service:1.2",
            "UPPERCASE/app",
        )

        for image in invalid_images:
            with self.subTest(image=image):
                self.assertFalse(is_valid_image_name(image))

    def test_split_registry_and_name_for_implicit_docker_hub_images(self) -> None:
        cases = {
            "nginx": (None, "nginx"),
            "gitea/gitea": (None, "gitea/gitea"),
            "  library/postgres  ": (None, "library/postgres"),
        }

        for image, expected in cases.items():
            with self.subTest(image=image):
                self.assertEqual(split_registry_and_name(image), expected)

    def test_split_registry_and_name_for_explicit_registries(self) -> None:
        cases = {
            "docker.io/library/nginx": ("docker.io", "library/nginx"),
            "ghcr.io/acme/example-app": ("ghcr.io", "acme/example-app"),
            "registry.example:5000/team/service": (
                "registry.example:5000",
                "team/service",
            ),
            "localhost/dev/app": ("localhost", "dev/app"),
        }

        for image, expected in cases.items():
            with self.subTest(image=image):
                self.assertEqual(split_registry_and_name(image), expected)

    def test_split_registry_and_name_returns_none_for_invalid_images(self) -> None:
        invalid_images = ("bad name", "nginx:latest", "repo@sha256:deadbeef")

        for image in invalid_images:
            with self.subTest(image=image):
                self.assertIsNone(split_registry_and_name(image))


if __name__ == "__main__":
    unittest.main()
