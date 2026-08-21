from __future__ import annotations

import unittest

from cli.contributing.mirror.model import ImageRef
from cli.contributing.mirror.providers import GHCRProvider


class TestGHCRProviderImageBase(unittest.TestCase):
    def setUp(self) -> None:
        self.image = ImageRef(
            role="web-app-nextcloud",
            service="app",
            name="nextcloud",
            version="31.0.0",
            source="docker.io/library/nextcloud:31.0.0",
            registry="docker.io",
        )

    def test_image_base_simple(self) -> None:
        provider = GHCRProvider("acme", "myrepo")
        self.assertEqual(
            provider.image_base(self.image),
            "ghcr.io/acme/myrepo/mirror/docker.io/nextcloud",
        )

    def test_image_base_with_slash_in_name(self) -> None:
        image = ImageRef(
            role="web-app-foo",
            service="svc",
            name="foo/bar",
            version="1.0",
            source="docker.io/foo/bar:1.0",
            registry="docker.io",
        )
        provider = GHCRProvider("acme", "myrepo")
        self.assertEqual(
            provider.image_base(image),
            "ghcr.io/acme/myrepo/mirror/docker.io/foo/bar",
        )

    def test_image_base_quay(self) -> None:
        image = ImageRef(
            role="web-app-keycloak",
            service="app",
            name="keycloak/keycloak",
            version="latest",
            source="quay.io/keycloak/keycloak:latest",
            registry="quay.io",
        )
        provider = GHCRProvider("acme", "myrepo")
        self.assertEqual(
            provider.image_base(image),
            "ghcr.io/acme/myrepo/mirror/quay.io/keycloak/keycloak",
        )

    def test_namespace_and_repository_are_lowercased(self) -> None:
        provider = GHCRProvider("ACME", "MyRepo")
        self.assertEqual(provider.namespace, "acme")
        self.assertEqual(provider.repository, "myrepo")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
